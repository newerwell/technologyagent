"""Fixture business time must not freeze credentials, deadlines or normal expiry."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from backend.app import bootstrap
from backend.app.api import inventory as inventory_api
from backend.app.agent.budget import RunBudget
from backend.app.config import Settings, load_settings
from backend.app.contracts.common import PageQuery, RequestContext, make_page
from backend.app.contracts.domain import Inventory, Part, Quote, ReplenishmentRequest, Supplier

BUSINESS_NOW = datetime(2026, 10, 23, 2, tzinfo=timezone.utc)
WALL_NOW = datetime(2035, 1, 1, tzinfo=timezone.utc)
URI = "mongodb://127.0.0.1:27028/?replicaSet=ta-rs&directConnection=true"


def settings(**overrides):
    return Settings(**{"mongodb_uri": URI, "mongodb_database": "technologyagent_test_clock",
                       "acceptance_business_now": BUSINESS_NOW, **overrides})


@pytest.mark.parametrize("overrides", [
    {"mongodb_database": "technologyagent_dev"},
    {"mongodb_database": "technologyagent_test_"},
    {"mongodb_uri": URI.replace("27028", "27027")},
    {"inventory_data_source": "local_snapshot"},
    {"parts_data_source": "remote_erp"},
    {"suppliers_data_source": "remote_erp"},
    {"orders_data_source": "remote_erp"},
    {"app_mode": "prod"},
    {"acceptance_business_now": datetime(2026, 10, 23, 2)},
])
def test_fixture_clock_rejects_daily_remote_prod_or_naive_configuration(overrides):
    with pytest.raises(ValidationError):
        settings(**overrides)


def test_fixture_clock_is_explicitly_loaded_and_reported_without_secrets():
    configured = load_settings({"MONGODB_URI": URI, "MONGODB_DATABASE": "technologyagent_test_clock",
                                "P09_ACCEPTANCE_BUSINESS_NOW": "2026-10-23T02:00:00Z"})
    assert configured.acceptance_business_now == BUSINESS_NOW
    assert configured.safe_summary()["acceptance_business_now"] == BUSINESS_NOW.isoformat()
    assert load_settings({}).acceptance_business_now is None


class AdvancingClock:
    def __init__(self):
        self.value = WALL_NOW

    def now(self):
        return self.value


class MemoryCatalog:
    async def list_parts(self, ids):
        return [Part(id="P001", code="P001", name="合成零件", unit="套", active=True)]

    async def list_quotes(self, ids):
        return [Quote(id="Q01", part_id="P001", supplier_id="S01", unit_price_cents=1200,
                      min_order_qty=1, lead_days=5, valid_until=datetime(2026, 12, 31, tzinfo=timezone.utc))]

    async def list_suppliers(self, ids):
        return [Supplier(id="S01", code="S01", name="合成供应商", status="active")]

    async def page_quotes(self, _name, _part, _supplier, page):
        return make_page(await self.list_quotes([]), 1, page.page, page.page_size)


class MemoryInventory:
    async def list_scope(self, ids, warehouse):
        return [Inventory(id="I001", part_id="P001", warehouse_id="W01", on_hand=20, reserved=5,
                          inbound=10, safety_stock=30, target_stock=80, version=1)]


class MemorySessions:
    def __init__(self):
        self.records = {}

    async def insert(self, record):
        self.records[record.token_hash] = record

    async def find(self, digest):
        return self.records.get(digest)


def container(monkeypatch, configured):
    clock = AdvancingClock()
    monkeypatch.setattr(bootstrap, "SystemClock", lambda: clock)
    monkeypatch.setattr(bootstrap, "CatalogRepository", lambda _mongo: MemoryCatalog())
    monkeypatch.setattr(bootstrap, "InventoryRepository", lambda _mongo: MemoryInventory())
    monkeypatch.setattr(bootstrap, "SessionRepository", lambda _mongo: MemorySessions())
    return bootstrap.build_container(configured), clock


@pytest.mark.asyncio
async def test_fixture_recommendation_stays_fixed_while_session_ttl_uses_wall_time(monkeypatch):
    app, wall = container(monkeypatch, settings())
    ctx = RequestContext(owner_id="clock-owner", request_id="clock-request")
    result = await app.replenishment.preview(ReplenishmentRequest(part_ids=["P001"], warehouse_id="W01"), ctx)
    assert result.lines[0].actionable and result.lines[0].quantity == 55
    page = await app.catalog.page_quotes(None, "P001", None, PageQuery())
    assert page.records[0].is_valid is True
    record, token = await app.sessions.create_local()
    assert record.created_at == WALL_NOW
    assert record.expires_at == WALL_NOW + timedelta(hours=24)
    assert await app.sessions.resolve(token) is not None
    wall.value += timedelta(hours=25)
    assert await app.sessions.resolve(token) is None
    assert app.clock.now() == wall.value
    result = await app.replenishment.preview(ReplenishmentRequest(part_ids=["P001"], warehouse_id="W01"), ctx)
    assert result.lines[0].actionable and result.lines[0].quantity == 55


@pytest.mark.asyncio
async def test_normal_recommendation_still_rejects_actually_expired_quote(monkeypatch):
    app, _wall = container(monkeypatch, settings(acceptance_business_now=None))
    result = await app.replenishment.preview(ReplenishmentRequest(part_ids=["P001"], warehouse_id="W01"),
                                           RequestContext(owner_id="clock-owner", request_id="normal"))
    assert result.lines[0].actionable is False


@pytest.mark.asyncio
async def test_fake_agent_actual_registry_keeps_business_clock_and_operational_metadata(monkeypatch):
    app, _wall = container(monkeypatch, settings())
    ctx = RequestContext(owner_id="clock-owner", request_id="registry-clock", run_id="registry-clock")
    registry = await app.chat._executor._registry_factory(ctx)
    result = await registry.invoke("replenishment_preview", {
        "part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7,
    }, ctx, RunBudget(ctx.run_id))
    assert result.ok
    assert result.data["lines"][0]["actionable"] is True
    assert result.data["lines"][0]["quantity"] == 55
    assert result.meta["as_of"] == WALL_NOW.isoformat()


@pytest.mark.asyncio
async def test_mcp_runtime_uses_same_fixture_business_clock_as_api(monkeypatch):
    from mcp_server import server
    from starlette.requests import Request

    wall = AdvancingClock()
    monkeypatch.setattr(server, "SystemClock", lambda: wall)
    monkeypatch.setattr(server, "CatalogRepository", lambda _mongo: MemoryCatalog())
    monkeypatch.setattr(server, "InventoryRepository", lambda _mongo: MemoryInventory())
    app, _ = container(monkeypatch, settings())
    runtime = server.McpRuntime(settings())
    ctx = RequestContext(owner_id="clock-owner", request_id="mcp-clock")
    request = Request({"type": "http", "http_version": "1.1", "method": "POST",
                       "scheme": "http", "path": "/api/replenishment/preview",
                       "raw_path": b"/api/replenishment/preview", "query_string": b"",
                       "headers": [], "server": ("testserver", 80),
                       "client": ("127.0.0.1", 12345)})
    api_result = await inventory_api.replenishment_preview(
        request, ReplenishmentRequest(part_ids=["P001"], warehouse_id="W01", max_lead_days=7), ctx, app)
    mcp_result = await server.replenishment_preview(
        runtime.inventory, ctx, wall.now(), part_ids=["P001"], warehouse_id="W01", max_lead_days=7)
    assert api_result.data.lines[0].actionable and api_result.data.lines[0].quantity == 55
    assert mcp_result["ok"] is True
    assert mcp_result["data"]["lines"][0]["actionable"] is True
    assert mcp_result["data"]["lines"][0]["quantity"] == 55
    assert mcp_result["meta"]["as_of"] == WALL_NOW.isoformat()
    assert api_result.data.model_dump(mode="json") == mcp_result["data"]
    assert runtime.clock.now() == WALL_NOW
