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
            InventoryService(inventory_repo),
            ReplenishmentService(catalog_repo, inventory_repo, self.clock),
        )
        self.tokens = McpTokenService(McpTokenRepository(self.mongo), self.clock)

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
        return await inventory_page(
            _runtime.inventory, ctx, _now(),
            warehouse_id=warehouse_id, part_name=part_name, page=page, page_size=page_size,
        )

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
        return await inventory_warning(
            _runtime.inventory, ctx, _now(),
            warehouse_id=warehouse_id, part_name=part_name, page=page, page_size=page_size,
        )

    @mcp.tool(name="inventory_get")
    async def inventory_get_tool(inventory_id: str) -> dict[str, Any]:
        """查询单条库存。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        return await inventory_get(_runtime.inventory, ctx, _now(), inventory_id=inventory_id)

    @mcp.tool(name="supplier_query")
    async def supplier_query_tool(
        name: str | None = None, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        """分页查询供应商。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        return await supplier_query(_runtime.catalog, ctx, _now(), name=name, page=page, page_size=page_size)

    @mcp.tool(name="supplier_get")
    async def supplier_get_tool(supplier_id: str) -> dict[str, Any]:
        """查询单个供应商。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        return await supplier_get(_runtime.catalog, ctx, _now(), supplier_id=supplier_id)

    @mcp.tool(name="part_search")
    async def part_search_tool(
        name: str | None = None, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        """分页搜索零件。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        return await part_search(_runtime.catalog, ctx, _now(), name=name, page=page, page_size=page_size)

    @mcp.tool(name="part_query")
    async def part_query_tool(part_id: str) -> dict[str, Any]:
        """查询单个零件。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        return await part_query(_runtime.catalog, ctx, _now(), part_id=part_id)

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
        request = DraftPrepareRequest(part_ids=part_ids, warehouse_id=warehouse_id,
                                      max_lead_days=max_lead_days)
        return {"ok": True, "data": await _runtime.drafts.prepare(request, ctx),
                "meta": {"scope": ctx.owner_id, "data_source": "local_seed"}}

    @mcp.tool(name="order_create")
    async def order_create_tool(draft_id: str, approval_id: str, idempotency_key: str) -> dict[str, Any]:
        """只通过 MutationService 提交；未批准审批会被拒绝。"""
        ctx = await _trusted_context()
        assert _runtime is not None
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
        order = await _runtime.orders.get(ctx.owner_id, order_id)
        if order is None:
            raise ToolError("NOT_FOUND: order not found")
        return {"ok": True, "data": order.model_dump(mode="json"),
                "meta": {"scope": ctx.owner_id, "data_source": "local_seed"}}

    @mcp.tool(name="order_page")
    async def order_page_tool(page: int = 1, page_size: int = 20) -> dict[str, Any]:
        """分页查询当前操作人的实际订单。"""
        ctx = await _trusted_context()
        assert _runtime is not None
        result = await _runtime.orders.page(ctx.owner_id, PageQuery(page=page, page_size=page_size))
        return {"ok": True, "data": result.model_dump(mode="json"),
                "meta": {"scope": ctx.owner_id, "data_source": "local_seed"}}

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
