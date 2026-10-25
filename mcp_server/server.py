"""P03 FastMCP Streamable HTTP 服务：只读工具 + 每 run Bearer token。

运行：uv run python -m mcp_server.server
服务地址：http://127.0.0.1:9030/mcp（端口由 MCP_PORT 配置）
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import uvicorn
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from backend.app.config import Settings, load_settings
from backend.app.contracts.common import RequestContext, SystemClock
from backend.app.repositories.catalog import CatalogRepository
from backend.app.repositories.indexes import ensure_indexes
from backend.app.repositories.inventory import InventoryRepository
from backend.app.repositories.mcp_tokens import McpTokenRepository
from backend.app.repositories.mongo import MongoResources
from backend.app.services.catalog import CatalogService, InventoryService
from backend.app.services.mcp_tokens import McpTokenService
from backend.app.services.replenishment import ReplenishmentService
from backend.app.services.drafts import DraftService
from backend.app.services.approvals import ApprovalService
from backend.app.services.mutations import MutationService
from backend.app.repositories.orders import OrderRepository
from backend.app.contracts.common import AppError, PageQuery
from backend.app.contracts.order_workflow import DraftPrepareRequest
from mcp_server.tools.catalog import (
    CatalogRuntime,
    part_query,
    part_search,
    quote_list,
    supplier_get,
    supplier_query,
)
from mcp_server.tools.inventory import (
    InventoryRuntime,
    inventory_get,
    inventory_page,
    inventory_warning,
    replenishment_preview,
)
from mcp_server.tools.specs import ALL_TOOL_SPECS
from mcp_server.tools.specs import P08_TOOL_SPECS, MUTATION_PREPARE_SPEC
from mcp_server.tools.business import dispatch as dispatch_business
from backend.app.services.inventory import InventoryMutationService
from backend.app.services.business_mutations import BusinessMutationService
from backend.app.integrations.local_provider import LocalProvider
from backend.app.integrations.erp_provider import ErpProvider
from backend.app.integrations.business_provider import UnavailableRemoteProvider
from backend.app.integrations.erp.client import ErpClient

logger = logging.getLogger(__name__)
_runtime: "McpRuntime | None" = None


class McpRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.mongo = MongoResources(settings)
        self.clock = SystemClock()
        catalog_repo = CatalogRepository(self.mongo)
        inventory_repo = InventoryRepository(self.mongo)
        self.orders = OrderRepository(self.mongo)
        self.drafts = DraftService(
            self.mongo, catalog_repo,
            ReplenishmentService(catalog_repo, inventory_repo, self.clock), self.clock,
        )
        self.mutations = MutationService(self.mongo, self.clock, inventory_repo, self.orders)
        catalog_service = CatalogService(catalog_repo, self.clock)
        self.catalog = CatalogRuntime(catalog_service)
        self.inventory = InventoryRuntime(
            InventoryService(inventory_repo, catalog_repo),
            ReplenishmentService(catalog_repo, inventory_repo, self.clock),
        )
        self.tokens = McpTokenService(McpTokenRepository(self.mongo), self.clock)
        self.inventory_mutations = InventoryMutationService(self.mongo, self.clock)
        self.business_mutations = BusinessMutationService(self.mongo, self.clock)
        self.approvals = ApprovalService(self.mongo, self.clock)
        if settings.erp_base_url:
            remote = ErpProvider(ErpClient(settings.erp_base_url,
                token=settings.erp_api_key.get_secret_value() if settings.erp_api_key else None,
                timeout_seconds=settings.erp_timeout_seconds),
                read_actions=frozenset({"supplier_page", "supplier_query", "supplier_get", "part_page", "part_search",
                    "part_query", "part_by_supplier", "inventory_page", "inventory_warning", "inventory_get",
                    "inventory_check", "order_page", "order_get", "order_search_details", "order_statistics"}))
        else:
            remote = UnavailableRemoteProvider()
        local = LocalProvider({"catalog": catalog_service if (catalog_service := CatalogService(catalog_repo, self.clock)) else None,
                               "inventory": self.inventory.inventory, "orders": self.orders})
        self.business_providers = {"suppliers": remote if settings.suppliers_data_source == "remote_erp" else LocalProvider(local.services, snapshot=settings.suppliers_data_source == "local_snapshot"),
            "parts": remote if settings.parts_data_source == "remote_erp" else LocalProvider(local.services, snapshot=settings.parts_data_source == "local_snapshot"),
            "inventory": remote if settings.inventory_data_source == "remote_erp" else LocalProvider(local.services, snapshot=settings.inventory_data_source == "local_snapshot"),
            "orders": remote if settings.orders_data_source == "remote_erp" else LocalProvider(local.services, snapshot=settings.orders_data_source == "local_snapshot")}

    async def start(self) -> None:
        await self.mongo.connect()
        await ensure_indexes(self.mongo.db)

    async def stop(self) -> None:
        await self.mongo.close()


async def _trusted_context() -> RequestContext:
    if _runtime is None:
        raise ToolError("MCP runtime is not ready")
    headers = get_http_headers(include={"authorization"})
    raw = headers.get("authorization", "")
    token = raw[7:].strip() if raw.lower().startswith("bearer ") else ""
    identity = await _runtime.tokens.resolve(token)
    if identity is None:
        raise ToolError("UNAUTHENTICATED: invalid or expired MCP token")
    return RequestContext(
        owner_id=identity.owner_id,
        request_id="mcp:" + identity.run_id,
        run_id=identity.run_id,
        actor=identity.actor,
        call_id="mcp_" + uuid4().hex,
    )


async def _business_call(name: str, payload: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    assert _runtime is not None
    module = ("suppliers" if name.startswith("supplier_") else "parts" if name.startswith("part_")
              else "inventory" if name.startswith("inventory_") else "orders" if name.startswith("order_") else None)
    provider = _runtime.business_providers.get(module) if module else None
    source = provider.capabilities.data_source if provider else "local_seed"
    meta = {"scope": ctx.owner_id, "request_id": ctx.request_id, "data_source": source,
            "as_of": _now().isoformat(), "call_id": ctx.call_id}
    try:
        data = await dispatch_business(_runtime, name, payload, ctx)
        return {"ok": True, "data": data, "error": None, "meta": meta}
    except AppError as exc:
        return {"ok": False, "data": None, "error": {"code": exc.code, "message": exc.message,
                "retryable": exc.retryable}, "meta": meta}
    except Exception as exc:
        code = getattr(exc, "code", "PROVIDER_UNAVAILABLE")
        return {"ok": False, "data": None, "error": {"code": code, "message": str(exc)[:300],
                "retryable": bool(getattr(exc, "retryable", False))}, "meta": meta}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_app(settings: Settings) -> Starlette:
    global _runtime

    @asynccontextmanager
    async def lifespan(_server):
        global _runtime
        runtime = McpRuntime(settings)
        await runtime.start()
        _runtime = runtime
        try:
            yield
        finally:
            _runtime = None
            await runtime.stop()

    mcp = FastMCP("technologyagent-readonly", lifespan=lifespan)

    @mcp.tool(name="inventory_page")
    async def inventory_page_tool(
        warehouse_id: str | None = None,
        part_name: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """分页查询库存及派生值。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        return await _business_call("inventory_page", {"warehouse_id": warehouse_id, "part_name": part_name,
            "page": page, "page_size": page_size}, ctx)

    @mcp.tool(name="inventory_warning")
    async def inventory_warning_tool(
        warehouse_id: str | None = None,
        part_name: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """只返回库存预警。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        return await _business_call("inventory_warning", {"warehouse_id": warehouse_id, "part_name": part_name,
            "page": page, "page_size": page_size}, ctx)

    @mcp.tool(name="inventory_get")
    async def inventory_get_tool(inventory_id: str) -> dict[str, Any]:
        """查询单条库存。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        return await _business_call("inventory_get", {"inventory_id": inventory_id}, ctx)

    @mcp.tool(name="supplier_query")
    async def supplier_query_tool(
        name: str | None = None, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        """分页查询供应商。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        return await _business_call("supplier_query", {"name": name, "page": page, "page_size": page_size}, ctx)

    @mcp.tool(name="supplier_get")
    async def supplier_get_tool(supplier_id: str) -> dict[str, Any]:
        """查询单个供应商。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        return await _business_call("supplier_get", {"supplier_id": supplier_id}, ctx)

    @mcp.tool(name="part_search")
    async def part_search_tool(
        name: str | None = None, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        """分页搜索零件。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        return await _business_call("part_search", {"name": name, "page": page, "page_size": page_size}, ctx)

    @mcp.tool(name="part_query")
    async def part_query_tool(part_id: str) -> dict[str, Any]:
        """查询单个零件。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        return await _business_call("part_query", {"part_id": part_id}, ctx)

    @mcp.tool(name="quote_list")
    async def quote_list_tool(
        part_id: str | None = None,
        part_name: str | None = None,
        supplier_id: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """分页查询报价。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        if any(_runtime.business_providers[module].capabilities.data_source not in {"local_seed", "local_snapshot"}
               for module in ("parts", "suppliers")):
            raise ToolError("UNSUPPORTED_OPERATION: quote_list uses the local quote supplement and cannot silently replace remote part/supplier data")
        return await quote_list(
            _runtime.catalog, ctx, _now(),
            part_id=part_id, part_name=part_name, supplier_id=supplier_id,
            page=page, page_size=page_size,
        )

    @mcp.tool(name="replenishment_preview")
    async def replenishment_preview_tool(
        part_ids: list[str], warehouse_id: str, max_lead_days: int | None = None
    ) -> dict[str, Any]:
        """计算补货预览，不创建订单。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        if any(_runtime.business_providers[module].capabilities.data_source not in {"local_seed", "local_snapshot"}
               for module in ("parts", "suppliers", "inventory", "orders")):
            raise ToolError("UNSUPPORTED_OPERATION: replenishment_preview requires a single local snapshot; mixed remote sources are not supported")
        return await replenishment_preview(
            _runtime.inventory, ctx, _now(),
            part_ids=part_ids, warehouse_id=warehouse_id, max_lead_days=max_lead_days,
        )

    @mcp.tool(name="draft_prepare")
    async def draft_prepare_tool(
        part_ids: list[str], warehouse_id: str | None = None,
        max_lead_days: int | None = None,
    ) -> dict[str, Any]:
        """准备可编辑草稿，不创建订单。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        if any(_runtime.business_providers[module].capabilities.data_source != "local_seed"
               for module in ("suppliers", "parts", "inventory", "orders")):
            raise ToolError("UNSUPPORTED_OPERATION: local draft preparation requires all source modules to use local_seed")
        request = DraftPrepareRequest(part_ids=part_ids, warehouse_id=warehouse_id,
                                      max_lead_days=max_lead_days)
        return {"ok": True, "data": await _runtime.drafts.prepare(request, ctx),
                "meta": {"scope": ctx.owner_id, "data_source": "local_seed"}}

    @mcp.tool(name="order_create")
    async def order_create_tool(draft_id: str, approval_id: str, idempotency_key: str) -> dict[str, Any]:
        """只通过 MutationService 提交；未批准审批会被拒绝。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        if _runtime.business_providers["orders"].capabilities.data_source != "local_seed":
            raise ToolError("UNSUPPORTED_OPERATION: ERP and snapshot order writes are not enabled")
        try:
            data = await _runtime.mutations.execute(draft_id, approval_id, idempotency_key, ctx)
        except AppError as exc:
            raise ToolError(f"{exc.code}: {exc.message}") from exc
        return {"ok": True, "data": data, "meta": {"scope": ctx.owner_id, "data_source": "local_seed"}}

    @mcp.tool(name="order_get")
    async def order_get_tool(order_id: str) -> dict[str, Any]:
        """查询当前操作人的实际订单。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        return await _business_call("order_get", {"order_id": order_id}, ctx)

    @mcp.tool(name="order_page")
    async def order_page_tool(page: int = 1, page_size: int = 20) -> dict[str, Any]:
        """分页查询当前操作人的实际订单。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        return await _business_call("order_page", {"page": page, "page_size": page_size}, ctx)

    from fastmcp.tools import FunctionTool

    def make_p08_handler(tool_name: str):
        async def handler(payload: dict[str, Any] | None = None,
                          approval_id: str | None = None,
                          idempotency_key: str | None = None) -> dict[str, Any]:
            ctx = await _trusted_context()
            assert _runtime is not None
            parameters = dict(payload or {})
            if approval_id is not None:
                parameters["approval_id"] = approval_id
            if idempotency_key is not None:
                parameters["idempotency_key"] = idempotency_key
            return await _business_call(tool_name, parameters, ctx)
        return handler

    for spec in P08_TOOL_SPECS:
        # Keep the MCP wire schema identical to the checked-in tool registry.
        # Inferring from the shared wrapper would expose payload as an untyped
        # object and silently discard each business tool's argument contract.
        mcp.add_tool(FunctionTool(name=spec.name, description=spec.description,
                                  parameters=spec.input_schema,
                                  fn=make_p08_handler(spec.name)))

    async def mutation_prepare_tool(action: str, payload: dict[str, Any]) -> dict[str, Any]:
        ctx = await _trusted_context()
        assert _runtime is not None
        try:
            data = await dispatch_business(_runtime, "mutation_prepare", {"action": action, "payload": payload}, ctx)
        except AppError as exc:
            raise ToolError(f"{exc.code}: {exc.message}") from exc
        return {"ok": True, "data": data, "meta": {"scope": ctx.owner_id, "data_source": "local_seed"}}
    mcp.tool(name="mutation_prepare")(mutation_prepare_tool)

    app = mcp.http_app(path="/mcp", stateless_http=True)

    async def health(_request):
        return JSONResponse({"ok": True, "component": "mcp", "tools": [s.name for s in ALL_TOOL_SPECS]})

    app.routes.append(Route("/health", health))
    return app


def main() -> None:
    settings = load_settings()
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.mcp_port)


if __name__ == "__main__":
    main()
