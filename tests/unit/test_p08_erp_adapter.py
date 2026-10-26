from decimal import Decimal

import httpx
import pytest

from backend.app.integrations.business_provider import UnsupportedProviderOperation
from backend.app.integrations.erp.client import ErpClient, ErpOutcomeUnknown
from backend.app.integrations.erp.mappings import (
    map_order,
    map_quote,
    normalize_page,
    yuan_to_cents,
)
from backend.app.integrations.erp_provider import ErpProvider
from backend.app.integrations.local_provider import LocalProvider
from mcp_server.tools.business import _map_remote


def test_yuan_mapping_is_exact_and_rejects_fractional_cent():
    assert yuan_to_cents("0.10") == 10
    with pytest.raises(ValueError):
        yuan_to_cents(Decimal("1.001"))


def test_page_mapping_does_not_claim_complete_when_total_contradicts_records():
    result = normalize_page({"records": [{"id": "A"}], "total": 0}, page=1, page_size=20)
    assert result.records == [{"id": "A"}]
    assert result.complete is False
    assert result.warning


@pytest.mark.parametrize("payload,page", [
    ({"records": [{"id": "A"}], "total": 21}, 2),
    ({"records": [], "total": 21}, 3),
])
def test_receiving_only_terminal_or_empty_page_never_proves_full_scope(payload, page):
    result = normalize_page(payload, page=page, page_size=20)
    assert result.complete is False


def test_duplicate_entity_ids_do_not_count_as_complete_records():
    result = normalize_page({"records": [{"id": "A"}, {"id": "A"}], "total": 2}, page=1, page_size=20)
    assert result.complete is False
    assert result.warning


def test_one_page_result_with_consistent_pages_and_total_is_complete():
    result = normalize_page({"records": [{"id": "A"}], "total": 1, "pages": 1}, page=1, page_size=20)
    assert result.complete is True


def test_remote_order_statistics_keep_statistics_shape_and_values():
    result = _map_remote("order_statistics", {
        "total": 30, "total_cents": 12345, "by_status": {"submitted": 30}, "scope_complete": True,
    }, {})
    assert result == {"total": 30, "total_cents": 12345, "by_status": {"submitted": 30}, "scope_complete": True}


@pytest.mark.asyncio
async def test_write_timeout_is_unknown_and_never_blindly_retried():
    created = []
    def handler(request):
        created.append(request.headers.get("Idempotency-Key"))
        raise httpx.ReadTimeout("response lost", request=request)
    client = ErpClient("https://erp.test", transport=httpx.MockTransport(handler))
    with pytest.raises(ErpOutcomeUnknown):
        await client.write("orders", {"amount": 100}, "corr-1")
    with pytest.raises(ErpOutcomeUnknown, match="lookup it"):
        await client.write("orders", {"amount": 100}, "corr-1")
    assert created == ["corr-1"]


@pytest.mark.asyncio
async def test_remote_provider_does_not_fall_back_and_denies_undeclared_write():
    transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "down"}))
    provider = ErpProvider(ErpClient("https://erp.test", transport=transport), read_actions=frozenset({"orders"}))
    with pytest.raises(httpx.HTTPStatusError):
        await provider.query("orders")
    with pytest.raises(UnsupportedProviderOperation):
        await provider.mutate("orders", {"x": 1}, approved=True, correlation_id="c")


def test_remote_missing_quote_fields_and_unknown_status_are_not_invented():
    quote = map_quote({"id": 5, "unit_price_yuan": "1.20"})
    assert quote["unit_price_cents"] == 120
    assert quote["min_order_qty"] is None and quote["lead_days"] is None
    assert set(quote["missing_fields"]) == {"min_order_qty", "lead_days", "valid_until"}
    order = map_order({"id": 7, "status": "ERP_NEW", "total_yuan": "0.10", "details": []})
    assert (order["id"], order["total_cents"], order["status"], order["raw_status"]) == ("7", 10, "unknown", "ERP_NEW")


@pytest.mark.asyncio
async def test_local_snapshot_rejects_write_before_dispatch():
    provider = LocalProvider({"mutations": object()}, snapshot=True)
    with pytest.raises(UnsupportedProviderOperation):
        await provider.mutate("supplier_create", {"code": "X", "name": "Y"}, approved=True)


@pytest.mark.asyncio
async def test_ordinary_lookup_404_is_not_authoritative_no_side_effect():
    transport = httpx.MockTransport(lambda request: httpx.Response(404))
    client = ErpClient("https://erp.test", transport=transport)
    with pytest.raises(ErpOutcomeUnknown):
        await client.lookup("corr-missing")
