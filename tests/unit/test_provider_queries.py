"""R5: remote page aggregation and DTO validation stay fail-closed."""

from __future__ import annotations

import pytest

from backend.app.contracts.common import AppError
from backend.app.integrations.provider_queries import ProviderQueries


class PageProvider:
    capabilities = type("Capabilities", (), {"data_source": "remote_erp"})()

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def query(self, operation, **params):
        self.calls.append((operation, params))
        page = params["page"]
        if page > len(self.pages):
            return {"records": [], "page": page, "page_size": params["page_size"],
                    "pages": len(self.pages) + 1, "total": len(self.pages) + 1}
        return self.pages[page - 1]


def supplier(supplier_id: str) -> dict:
    return {"id": supplier_id, "code": supplier_id, "name": "供应商", "status": "active"}


def page(rows, *, page, pages, total, page_size=1):
    return {"records": rows, "page": page, "page_size": page_size,
            "pages": pages, "total": total}


@pytest.mark.asyncio
async def test_remote_page_aggregates_all_pages_but_returns_requested_slice():
    provider = PageProvider([
        page([supplier("S01")], page=1, pages=2, total=2),
        page([supplier("S02")], page=2, pages=2, total=2),
    ])
    result = await ProviderQueries().page(provider, "supplier_page", {"page": 2, "page_size": 1}, "supplier")
    assert result.total == 2
    assert [row.id for row in result.records] == ["S02"]
    assert [params["page"] for _, params in provider.calls] == [1, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize("pages", [
    [page([supplier("S01")], page=1, pages=2, total=2)],
    [page([supplier("S01")], page=1, pages=2, total=2), page([supplier("S01")], page=2, pages=2, total=2)],
    [page([supplier("S01")], page=1, pages=1, total=2)],
    [page([supplier("S01")], page=2, pages=1, total=1)],
])
async def test_remote_page_rejects_missing_duplicate_or_contradictory_pages(pages):
    with pytest.raises(AppError, match="incomplete|duplicate|page"):
        await ProviderQueries().page(PageProvider(pages), "supplier_page", {"page": 1, "page_size": 1}, "supplier")


@pytest.mark.asyncio
async def test_remote_page_rejects_missing_required_fields_instead_of_defaulting():
    provider = PageProvider([page([{"id": "S01", "code": "S01", "name": "供应商"}],
                                  page=1, pages=1, total=1)])
    with pytest.raises(AppError, match="status"):
        await ProviderQueries().page(provider, "supplier_page", {"page": 1, "page_size": 1}, "supplier")


@pytest.mark.asyncio
async def test_remote_page_stops_when_remaining_budget_is_exhausted():
    provider = PageProvider([
        page([supplier("S01")], page=1, pages=2, total=2),
        page([supplier("S02")], page=2, pages=2, total=2),
    ])
    with pytest.raises(AppError, match="budget"):
        await ProviderQueries().page(provider, "supplier_page", {"page": 1, "page_size": 1}, "supplier",
                                      remaining_budget=0)
    assert provider.calls == []


@pytest.mark.asyncio
async def test_remote_page_does_not_start_next_request_after_budget_expires():
    import asyncio

    class SlowProvider(PageProvider):
        async def query(self, operation, **params):
            await asyncio.sleep(0.02)
            return await super().query(operation, **params)

    provider = SlowProvider([
        page([supplier("S01")], page=1, pages=2, total=2),
        page([supplier("S02")], page=2, pages=2, total=2),
    ])
    with pytest.raises(AppError, match="budget"):
        await ProviderQueries().page(provider, "supplier_page", {"page": 1, "page_size": 1}, "supplier",
                                      remaining_budget=0.01)
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_empty_remote_result_allows_only_first_page():
    provider = PageProvider([page([], page=1, pages=0, total=0, page_size=10)])
    result = await ProviderQueries().page(provider, "supplier_page", {"page": 1, "page_size": 10}, "supplier")
    assert result.total == 0 and result.pages == 0 and result.records == []
    with pytest.raises(AppError, match="out of range"):
        await ProviderQueries().page(provider, "supplier_page", {"page": 2, "page_size": 10}, "supplier")


@pytest.mark.asyncio
async def test_remote_page_requires_all_pagination_fields_and_rejects_limit_boundary():
    provider = PageProvider([{"records": [supplier("S01")], "total": 1, "page": 1, "page_size": 1}])
    with pytest.raises(AppError, match="pages"):
        await ProviderQueries().page(provider, "supplier_page", {"page": 1, "page_size": 1}, "supplier")

    provider = PageProvider([page([supplier("S01")], page=1, pages=100, total=100)])
    with pytest.raises(AppError, match="safety limit"):
        await ProviderQueries().page(provider, "supplier_page", {"page": 1, "page_size": 1}, "supplier")


@pytest.mark.asyncio
async def test_remote_inventory_requires_target_version_and_exact_integer_facts():
    valid = {"id": "I01", "part_id": "P01", "warehouse_id": "W01", "on_hand": 8,
             "reserved": 2, "inbound": 1, "safety_stock": 4, "target_stock": 10, "version": 2}
    provider = PageProvider([page([valid], page=1, pages=1, total=1)])
    result = await ProviderQueries().page(provider, "inventory_page", {"page": 1, "page_size": 1}, "inventory")
    assert result.records[0].shortage == 3
    invalid = {**valid, "target_stock": 10.5}
    provider = PageProvider([page([invalid], page=1, pages=1, total=1)])
    with pytest.raises(AppError, match="REMOTE_DATA_INVALID|integer|missing required"):
        await ProviderQueries().page(provider, "inventory_page", {"page": 1, "page_size": 1}, "inventory")


@pytest.mark.asyncio
async def test_remote_part_requires_source_unit_and_boolean_active_state():
    valid = {"id": "P01", "code": "P01", "name": "物料", "unit": "件", "active": True}
    provider = PageProvider([page([valid], page=1, pages=1, total=1)])
    result = await ProviderQueries().page(provider, "part_page", {"page": 1, "page_size": 1}, "part")
    assert result.records[0].unit == "件"
    invalid = {key: value for key, value in valid.items() if key != "unit"}
    provider = PageProvider([page([invalid], page=1, pages=1, total=1)])
    with pytest.raises(AppError, match="unit"):
        await ProviderQueries().page(provider, "part_page", {"page": 1, "page_size": 1}, "part")


@pytest.mark.asyncio
async def test_remote_order_requires_complete_existing_order_dto():
    order = {"id": "O01", "number": "PO-01", "owner_id": "owner", "draft_id": "D01",
             "supplier_id": "S01", "warehouse_id": "W01", "status": "submitted",
             "total_cents": 1200, "version": 1, "created_at": "2026-11-08T00:00:00Z",
             "items": [{"part_id": "P01", "quantity": 1, "quote_id": "Q01",
                        "unit_price_yuan": "12.00", "line_total_yuan": "12.00", "received_qty": 0}]}
    provider = PageProvider([page([order], page=1, pages=1, total=1)])
    result = await ProviderQueries().page(provider, "order_page", {"page": 1, "page_size": 1}, "order")
    assert result.records[0].total_cents == 1200
    incomplete = {**order, "items": [{key: value for key, value in order["items"][0].items()
                                       if key != "quote_id"}]}
    provider = PageProvider([page([incomplete], page=1, pages=1, total=1)])
    with pytest.raises(AppError, match="quote_id"):
        await ProviderQueries().page(provider, "order_page", {"page": 1, "page_size": 1}, "order")
