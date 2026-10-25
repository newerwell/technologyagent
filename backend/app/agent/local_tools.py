"""离线/脚本模式的本地只读 registry；与 MCP handler 共用同一业务函数。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.agent.budget import RunBudget
from backend.app.contracts.common import AppError, Clock, RequestContext
from backend.app.ports.tools import ToolResult, ToolSpec
from backend.app.repositories.catalog import CatalogRepository
from backend.app.repositories.inventory import InventoryRepository
from backend.app.services.catalog import CatalogService, InventoryService
from backend.app.services.replenishment import ReplenishmentService
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
from mcp_server.tools.specs import TOOL_SPECS


class LocalToolRegistry:
    def __init__(self, catalog_repo: CatalogRepository, inventory_repo: InventoryRepository, clock: Clock) -> None:
        self._clock = clock
        self._catalog = CatalogRuntime(CatalogService(catalog_repo, clock))
        self._inventory = InventoryRuntime(
            InventoryService(inventory_repo, catalog_repo),
            ReplenishmentService(catalog_repo, inventory_repo, clock),
        )

    def available(self, ctx: RequestContext) -> list[ToolSpec]:
        return list(TOOL_SPECS)

    async def invoke(
        self, name: str, arguments: dict[str, Any], ctx: RequestContext, budget: RunBudget
    ) -> ToolResult:
        if name not in {spec.name for spec in TOOL_SPECS}:
            return ToolResult(ok=False, error={"code": "UNKNOWN_TOOL", "message": name}, call_id=ctx.call_id or "")
        now = self._clock.now()
        handlers = {
            "inventory_page": lambda: inventory_page(self._inventory, ctx, now, **arguments),
            "inventory_warning": lambda: inventory_warning(self._inventory, ctx, now, **arguments),
            "inventory_get": lambda: inventory_get(self._inventory, ctx, now, **arguments),
            "supplier_query": lambda: supplier_query(self._catalog, ctx, now, **arguments),
            "supplier_get": lambda: supplier_get(self._catalog, ctx, now, **arguments),
            "part_search": lambda: part_search(self._catalog, ctx, now, **arguments),
            "part_query": lambda: part_query(self._catalog, ctx, now, **arguments),
            "quote_list": lambda: quote_list(self._catalog, ctx, now, **arguments),
            "replenishment_preview": lambda: replenishment_preview(
                self._inventory, ctx, now, **arguments
            ),
        }
        try:
            payload = await handlers[name]()
        except AppError as exc:
            return ToolResult(
                ok=False,
                error={"code": exc.code, "message": exc.message, "retryable": exc.retryable},
                call_id=ctx.call_id or "",
            )
        except (TypeError, ValueError) as exc:
            return ToolResult(
                ok=False,
                error={"code": "INVALID_ARGUMENTS", "message": str(exc)},
                call_id=ctx.call_id or "",
            )
        return ToolResult(
            ok=bool(payload.get("ok")),
            data=payload.get("data"),
            error=payload.get("error"),
            meta=payload.get("meta") or {},
            call_id=ctx.call_id or "",
        )
