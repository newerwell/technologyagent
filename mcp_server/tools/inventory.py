"""P03 库存与补货类只读工具；复用 P01 服务/纯规则。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.app.contracts.common import AppError, RequestContext
from backend.app.contracts.domain import InventoryQuery, ReplenishmentRequest
from backend.app.services.catalog import InventoryService
from backend.app.services.replenishment import ReplenishmentService
from mcp_server.tools.catalog import _fail, _ok


@dataclass(frozen=True, slots=True)
class InventoryRuntime:
    inventory: InventoryService
    replenishment: ReplenishmentService


async def inventory_page(
    runtime: InventoryRuntime,
    ctx: RequestContext,
    now: datetime,
    *,
    warehouse_id: str | None = None,
    part_name: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    try:
        result = await runtime.inventory.page(
            InventoryQuery(
                warehouse_id=warehouse_id,
                part_name=part_name,
                page=page,
                page_size=page_size,
            )
        )
        return _ok(result.model_dump(mode="json"), ctx, now)
    except AppError as exc:
        return _fail(exc, ctx, now)


async def inventory_warning(
    runtime: InventoryRuntime,
    ctx: RequestContext,
    now: datetime,
    *,
    warehouse_id: str | None = None,
    part_name: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    try:
        result = await runtime.inventory.warnings(
            InventoryQuery(
                warehouse_id=warehouse_id,
                part_name=part_name,
                page=page,
                page_size=page_size,
            )
        )
        return _ok(result.model_dump(mode="json"), ctx, now)
    except AppError as exc:
        return _fail(exc, ctx, now)


async def inventory_get(
    runtime: InventoryRuntime, ctx: RequestContext, now: datetime, *, inventory_id: str
) -> dict[str, Any]:
    try:
        return _ok((await runtime.inventory.get(inventory_id)).model_dump(mode="json"), ctx, now)
    except AppError as exc:
        return _fail(exc, ctx, now)


async def replenishment_preview(
    runtime: InventoryRuntime,
    ctx: RequestContext,
    now: datetime,
    *,
    part_ids: list[str],
    warehouse_id: str,
    max_lead_days: int | None = None,
) -> dict[str, Any]:
    try:
        result = await runtime.replenishment.preview(
            ReplenishmentRequest(
                part_ids=part_ids,
                warehouse_id=warehouse_id,
                max_lead_days=max_lead_days,
            ),
            ctx,
        )
        return _ok(result.model_dump(mode="json"), ctx, now)
    except AppError as exc:
        return _fail(exc, ctx, now)
