"""P01 目录查询 API：零件、供应商、报价。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from backend.app.api.dependencies import envelope, get_container, get_context
from backend.app.bootstrap import Container
from backend.app.contracts.common import Envelope, Page, PageQuery, RequestContext, make_page
from backend.app.contracts.domain import Part, QuoteView, Supplier

router = APIRouter(prefix="/api", tags=["catalog"])
DATA_SOURCE = "local_seed"
SCOPE = "shared_catalog"


@router.get("/parts", response_model=Envelope[Page[Part]])
async def parts(
    request: Request,
    name: str | None = Query(default=None),
    part_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[Page[Part]]:
    _ = ctx
    query = PageQuery(page=page, page_size=page_size)
    if part_id:
        part = await container.catalog.get_part(part_id)
        if name and name.lower() not in part.name.lower():
            result = make_page([], 0, page, page_size)
        else:
            result = make_page([part] if page == 1 else [], 1, page, page_size)
    else:
        result = await container.catalog.search_parts(name, query)
    return envelope(result, request, container, scope=SCOPE, data_source=DATA_SOURCE)


@router.get("/suppliers", response_model=Envelope[Page[Supplier]])
async def suppliers(
    request: Request,
    name: str | None = Query(default=None),
    supplier_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[Page[Supplier]]:
    _ = ctx
    query = PageQuery(page=page, page_size=page_size)
    if supplier_id:
        supplier = await container.catalog.get_supplier(supplier_id)
        if name and name.lower() not in supplier.name.lower():
            result = make_page([], 0, page, page_size)
        else:
            result = make_page([supplier] if page == 1 else [], 1, page, page_size)
    else:
        result = await container.catalog.search_suppliers(name, query)
    return envelope(result, request, container, scope=SCOPE, data_source=DATA_SOURCE)


@router.get("/quotes", response_model=Envelope[Page[QuoteView]])
async def quotes(
    request: Request,
    part_name: str | None = Query(default=None),
    part_id: str | None = Query(default=None),
    supplier_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[Page[QuoteView]]:
    _ = ctx
    result = await container.catalog.page_quotes(
        part_name,
        part_id,
        supplier_id,
        PageQuery(page=page, page_size=page_size),
    )
    return envelope(result, request, container, scope=SCOPE, data_source=DATA_SOURCE)
