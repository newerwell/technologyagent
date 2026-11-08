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
        def __init__(self):
            super().__init__([
                page([supplier("S01")], page=1, pages=2, total=2),
                page([supplier("S02")], page=2, pages=2, total=2),
            ])
            self.started_pages = []
            self.closed_reads = 0

        async def query(self, operation, **params):
            self.started_pages.append(params["page"])
            try:
                await asyncio.sleep(0.02)
                return await super().query(operation, **params)
            finally:
                self.closed_reads += 1

    provider = SlowProvider()
    with pytest.raises(AppError, match="budget"):
        await ProviderQueries().page(provider, "supplier_page", {"page": 1, "page_size": 1}, "supplier",
                                      remaining_budget=0.01)
    assert provider.started_pages == [1]
    assert provider.closed_reads == 1


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
@pytest.mark.parametrize("identity_key", ["id", "inventory_id"])
@pytest.mark.parametrize("quantity_key", ["on_hand", "quantity", "stock_qty"])
async def test_remote_inventory_supported_aliases_preserve_complete_facts(identity_key, quantity_key):
    record = {identity_key: "I01", "part_id": "P01", "warehouse_id": "W01", quantity_key: 8,
              "reserved": 2, "inbound": 1, "safety_stock": 4, "target_stock": 10, "version": 2}
    provider = PageProvider([page([record], page=1, pages=1, total=1)])

    result = await ProviderQueries().page(provider, "inventory_page", {"page": 1, "page_size": 1}, "inventory")

    inventory = result.records[0]
    assert (inventory.id, inventory.part_id, inventory.warehouse_id) == ("I01", "P01", "W01")
    assert (inventory.on_hand, inventory.available, inventory.projected, inventory.shortage) == (8, 6, 7, 3)
    assert inventory.warning is False


@pytest.mark.asyncio
async def test_remote_inventory_zero_on_hand_is_not_treated_as_missing_or_replaced_by_alias():
    record = {"id": "I01", "part_id": "P01", "warehouse_id": "W01", "on_hand": 0, "quantity": 8,
              "reserved": 0, "inbound": 1, "safety_stock": 4, "target_stock": 10, "version": 2}
    provider = PageProvider([page([record], page=1, pages=1, total=1)])

    result = await ProviderQueries().page(provider, "inventory_page", {"page": 1, "page_size": 1}, "inventory")

    inventory = result.records[0]
    assert (inventory.on_hand, inventory.available, inventory.projected, inventory.shortage) == (0, 0, 1, 9)
    assert inventory.warning is True


@pytest.mark.asyncio
@pytest.mark.parametrize("field,aliases", [
    ("id", ("id", "inventory_id")),
    ("on_hand", ("on_hand", "quantity", "stock_qty")),
])
async def test_remote_inventory_rejects_when_all_required_aliases_are_missing(field, aliases):
    record = {"id": "I01", "part_id": "P01", "warehouse_id": "W01", "on_hand": 8,
              "reserved": 2, "inbound": 1, "safety_stock": 4, "target_stock": 10, "version": 2}
    for key in aliases:
        record.pop(key, None)
    provider = PageProvider([page([record], page=1, pages=1, total=1)])

    with pytest.raises(AppError) as exc_info:
        await ProviderQueries().page(provider, "inventory_page", {"page": 1, "page_size": 1}, "inventory")
    assert exc_info.value.code == "REMOTE_DATA_INVALID"


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("on_hand", None), ("quantity", None), ("stock_qty", True), ("reserved", -1),
    ("inbound", -1), ("safety_stock", -1), ("target_stock", -1), ("version", 0),
])
async def test_remote_inventory_rejects_null_bool_negative_and_invalid_version(field, value):
    record = {"id": "I01", "part_id": "P01", "warehouse_id": "W01", "on_hand": 8,
              "reserved": 2, "inbound": 1, "safety_stock": 4, "target_stock": 10, "version": 2}
    if field in {"quantity", "stock_qty"}:
        record.pop("on_hand")
    record[field] = value
    provider = PageProvider([page([record], page=1, pages=1, total=1)])

    with pytest.raises(AppError) as exc_info:
        await ProviderQueries().page(provider, "inventory_page", {"page": 1, "page_size": 1}, "inventory")
    assert exc_info.value.code == "REMOTE_DATA_INVALID"


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


@pytest.mark.asyncio
async def test_remote_last_page_cannot_succeed_after_deadline():
    import asyncio

    class SlowProvider(PageProvider):
        def __init__(self):
            super().__init__([])
            self.started = False
            self.closed = False

        async def query(self, operation, **params):
            self.started = True
            try:
                await asyncio.sleep(0.04)
                self.calls.append((operation, params))
                return page([supplier("S01")], page=1, pages=1, total=1)
            finally:
                self.closed = True

    provider = SlowProvider()
    with pytest.raises(AppError) as raised:
        await ProviderQueries(max_query_seconds=0.01).page(
            provider, "supplier_page", {"page": 1, "page_size": 1}, "supplier", remaining_budget=0.01)
    assert raised.value.code == "DEPENDENCY_UNAVAILABLE"
    assert raised.value.http_status == 503 and raised.value.retryable is True
    assert provider.started and provider.closed


@pytest.mark.asyncio
async def test_remote_get_uses_total_deadline():
    import asyncio

    class SlowProvider:
        capabilities = PageProvider([]).capabilities

        def __init__(self):
            self.started = False
            self.closed = False

        async def query(self, operation, **params):
            self.started = True
            try:
                await asyncio.sleep(0.04)
                return supplier("S01")
            finally:
                self.closed = True

    provider = SlowProvider()
    with pytest.raises(AppError) as raised:
        await ProviderQueries(max_query_seconds=0.01).get(
            provider, "supplier_get", {"supplier_id": "S01"}, "supplier", remaining_budget=0.01)
    assert raised.value.code == "DEPENDENCY_UNAVAILABLE"
    assert raised.value.http_status == 503 and raised.value.retryable is True
    assert provider.started and provider.closed


@pytest.mark.asyncio
async def test_remote_get_uses_service_timeout_without_explicit_budget():
    import asyncio

    class SlowProvider:
        async def query(self, operation, **params):
            await asyncio.sleep(0.04)
            return supplier("S01")

    with pytest.raises(AppError) as raised:
        await ProviderQueries(max_query_seconds=0.01).get(
            SlowProvider(), "supplier_get", {"supplier_id": "S01"}, "supplier")
    assert raised.value.code == "DEPENDENCY_UNAVAILABLE"
    assert raised.value.retryable is True


@pytest.mark.asyncio
async def test_remote_all_records_shares_one_deadline_across_pages(monkeypatch):
    import backend.app.integrations.provider_queries as provider_queries

    class Clock:
        now = 100.0

        def monotonic(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(provider_queries.time, "monotonic", clock.monotonic)

    class AdvancingProvider(PageProvider):
        async def query(self, operation, **params):
            self.calls.append((operation, params))
            clock.now += 0.006
            current = params["page"]
            first_id = (current - 1) * 100
            rows = [supplier(f"S{index:03}") for index in range(first_id, first_id + 100)]
            return page(rows, page=current, pages=2, total=200,
                        page_size=params["page_size"])

    provider = AdvancingProvider([])
    with pytest.raises(AppError) as raised:
        await ProviderQueries(max_query_seconds=0.01).all_records(
            provider, "supplier_page", {}, "supplier")
    assert raised.value.code == "DEPENDENCY_UNAVAILABLE"
    assert [params["remaining_budget"] for _, params in provider.calls] == pytest.approx([0.01, 0.004])
    assert [params["page"] for _, params in provider.calls] == [1, 2]


@pytest.mark.asyncio
async def test_remote_timeout_cancels_and_closes_read():
    import asyncio

    class SlowProvider(PageProvider):
        def __init__(self):
            super().__init__([])
            self.started = asyncio.Event()
            self.closed = asyncio.Event()

        async def query(self, operation, **params):
            self.started.set()
            try:
                await asyncio.sleep(1)
            finally:
                self.closed.set()

    provider = SlowProvider()
    with pytest.raises(AppError) as raised:
        await ProviderQueries(max_query_seconds=0.01).page(
            provider, "supplier_page", {"page": 1, "page_size": 1}, "supplier")
    assert raised.value.code == "DEPENDENCY_UNAVAILABLE"
    assert provider.started.is_set() and provider.closed.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("max_query_seconds", [0, -0.1, float("nan"), float("inf")])
async def test_remote_read_rejects_invalid_service_deadline_before_request(max_query_seconds):
    provider = PageProvider([page([supplier("S01")], page=1, pages=1, total=1)])
    with pytest.raises(AppError) as raised:
        await ProviderQueries(max_query_seconds=max_query_seconds).page(
            provider, "supplier_page", {"page": 1, "page_size": 1}, "supplier")
    assert raised.value.code == "DEPENDENCY_UNAVAILABLE"
    assert provider.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("remaining_budget", [0, -0.1, float("nan"), float("inf")])
async def test_remote_read_rejects_invalid_run_deadline_before_request(remaining_budget):
    provider = PageProvider([page([supplier("S01")], page=1, pages=1, total=1)])
    with pytest.raises(AppError) as raised:
        await ProviderQueries(max_query_seconds=1).page(
            provider, "supplier_page", {"page": 1, "page_size": 1}, "supplier",
            remaining_budget=remaining_budget)
    assert raised.value.code == "DEPENDENCY_UNAVAILABLE"
    assert provider.calls == []
