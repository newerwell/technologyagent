"""P03 目录类只读工具：零件、供应商、报价。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.app.contracts.common import AppError, PageQuery, RequestContext
from backend.app.services.catalog import CatalogService


@dataclass(frozen=True, slots=True)
class CatalogRuntime:
    catalog: CatalogService


def _meta(ctx: RequestContext, now: datetime) -> dict[str, Any]:
    return {
        "request_id": ctx.request_id,
        "data_source": "local_seed",
        "scope": "shared_catalog",
        "as_of": now.isoformat(),
        "call_id": ctx.call_id,
    }


def _ok(data: Any, ctx: RequestContext, now: datetime) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None, "meta": _meta(ctx, now)}


def _fail(exc: AppError, ctx: RequestContext, now: datetime) -> dict[str, Any]:
    return {
        "ok": False,
        "data": None,
        "error": {"code": exc.code, "message": exc.message, "retryable": exc.retryable},
        "meta": _meta(ctx, now),
    }


async def part_search(
    runtime: CatalogRuntime,
    ctx: RequestContext,
    now: datetime,
    *,
    name: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    try:
        result = await runtime.catalog.search_parts(name, PageQuery(page=page, page_size=page_size))
        return _ok(result.model_dump(mode="json"), ctx, now)
    except AppError as exc:
        return _fail(exc, ctx, now)


async def part_query(
    runtime: CatalogRuntime, ctx: RequestContext, now: datetime, *, part_id: str
) -> dict[str, Any]:
    try:
        return _ok((await runtime.catalog.get_part(part_id)).model_dump(mode="json"), ctx, now)
    except AppError as exc:
        return _fail(exc, ctx, now)


async def supplier_query(
    runtime: CatalogRuntime,
    ctx: RequestContext,
    now: datetime,
    *,
    name: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    try:
        result = await runtime.catalog.search_suppliers(name, PageQuery(page=page, page_size=page_size))
        return _ok(result.model_dump(mode="json"), ctx, now)
    except AppError as exc:
        return _fail(exc, ctx, now)


async def supplier_get(
    runtime: CatalogRuntime, ctx: RequestContext, now: datetime, *, supplier_id: str
) -> dict[str, Any]:
    try:
        return _ok((await runtime.catalog.get_supplier(supplier_id)).model_dump(mode="json"), ctx, now)
    except AppError as exc:
        return _fail(exc, ctx, now)


async def quote_list(
    runtime: CatalogRuntime,
    ctx: RequestContext,
    now: datetime,
    *,
    part_id: str | None = None,
    part_name: str | None = None,
    supplier_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    try:
        result = await runtime.catalog.page_quotes(
            part_name, part_id, supplier_id, PageQuery(page=page, page_size=page_size)
        )
        return _ok(result.model_dump(mode="json"), ctx, now)
    except AppError as exc:
        return _fail(exc, ctx, now)
