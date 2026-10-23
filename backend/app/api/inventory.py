"""P01 库存查询、预警、汇总与补货预览 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from backend.app.api.dependencies import envelope, get_container, get_context
from backend.app.bootstrap import Container
from backend.app.contracts.common import Envelope, Page, RequestContext
from backend.app.contracts.domain import (
    InventoryQuery,
    InventorySummary,
    InventoryView,
    PreviewResult,
    ReplenishmentRequest,
)

router = APIRouter(prefix="/api", tags=["inventory"])
DATA_SOURCE = "local_seed"
SCOPE = "shared_catalog"


@router.get("/inventory", response_model=Envelope[Page[InventoryView]])
async def inventory(
    request: Request,
    warehouse_id: str | None = Query(default=None),
    part_name: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[Page[InventoryView]]:
    _ = ctx
    result = await container.inventory.page(
        InventoryQuery(
            warehouse_id=warehouse_id,
            part_name=part_name,
            page=page,
            page_size=page_size,
        )
    )
    return envelope(result, request, container, scope=SCOPE, data_source=DATA_SOURCE)


@router.get("/inventory/warnings", response_model=Envelope[Page[InventoryView]])
async def inventory_warnings(
    request: Request,
    warehouse_id: str | None = Query(default=None),
    part_name: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[Page[InventoryView]]:
    _ = ctx
    result = await container.inventory.warnings(
        InventoryQuery(
            warehouse_id=warehouse_id,
            part_name=part_name,
            page=page,
            page_size=page_size,
        )
    )
    return envelope(result, request, container, scope=SCOPE, data_source=DATA_SOURCE)


@router.get("/inventory/summary", response_model=Envelope[InventorySummary])
async def inventory_summary(
    request: Request,
    warehouse_id: str | None = Query(default=None),
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[InventorySummary]:
    _ = ctx
    result = await container.inventory.summary(warehouse_id)
    return envelope(result, request, container, scope=SCOPE, data_source=DATA_SOURCE)


@router.post("/replenishment/preview", response_model=Envelope[PreviewResult])
async def replenishment_preview(
    request: Request,
    payload: ReplenishmentRequest,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[PreviewResult]:
    result = await container.replenishment.preview(payload, ctx)
    return envelope(result, request, container, scope=SCOPE, data_source=DATA_SOURCE)
