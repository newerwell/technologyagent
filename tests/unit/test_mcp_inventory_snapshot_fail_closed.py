from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import mcp_server.tools.inventory as inventory_tools
import mcp_server.tools.pagination as pagination
import mcp_server.server as mcp_server
from backend.app.contracts.common import RequestContext


class _PageResult:
    def model_dump(self, mode="python"):
        return {
            "records": [{"id": "I001", "part_id": "P001", "warehouse_id": "W01"}],
            "total": 1,
            "page": 1,
            "page_size": 20,
            "pages": 1,
        }


class _Inventory:
    snapshot_meta = None

    async def page(self, _query):
        return _PageResult()

    async def warnings(self, _query):
        return _PageResult()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", [inventory_tools.inventory_page, inventory_tools.inventory_warning])
async def test_inventory_mcp_tool_rejects_success_when_full_snapshot_cannot_be_proven(monkeypatch, tool):
    async def no_provable_snapshot(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pagination, "inventory_page_snapshot_id", no_provable_snapshot)
    runtime = SimpleNamespace(inventory=_Inventory())
    result = await tool(
        runtime, RequestContext("owner", "request"), datetime(2026, 10, 24, tzinfo=timezone.utc),
        warehouse_id="W01",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "INCOMPLETE_SNAPSHOT"
    assert result["meta"]["data_source"] == "local_seed"


@pytest.mark.asyncio
async def test_registered_mcp_business_entry_fails_closed_if_snapshot_is_unprovable(monkeypatch):
    provider = SimpleNamespace(capabilities=SimpleNamespace(data_source="local_seed"))
    runtime = SimpleNamespace(
        business_providers={"inventory": provider},
        inventory=SimpleNamespace(inventory=_Inventory()),
    )
    monkeypatch.setattr(mcp_server, "_runtime", runtime)

    async def dispatch(*_args, **_kwargs):
        return _PageResult().model_dump(mode="json")

    async def no_provable_snapshot(*_args, **_kwargs):
        return None

    monkeypatch.setattr(mcp_server, "dispatch_business", dispatch)
    monkeypatch.setattr(pagination, "inventory_page_snapshot_id", no_provable_snapshot)
    result = await mcp_server._business_call(
        "inventory_page", {"warehouse_id": "W01", "page": 1, "page_size": 20},
        RequestContext("owner", "request"),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "INCOMPLETE_SNAPSHOT"
    assert result["meta"]["data_source"] == "local_seed"


def test_mcp_snapshot_unsupported_error_preserves_snapshot_source_metadata():
    runtime = SimpleNamespace(inventory=SimpleNamespace(inventory=SimpleNamespace(snapshot_meta={
        "data_source": "local_snapshot", "as_of": "2026-10-24T10:00:00+00:00", "completeness": "unknown",
    })))
    payload = {"ok": False, "error": {"code": "UNSUPPORTED_OPERATION"}, "meta": {"data_source": "local_seed"}}

    result = mcp_server._preserve_snapshot_failure_metadata(payload, runtime)

    assert result["meta"]["data_source"] == "local_snapshot"
    assert result["meta"]["as_of"] == "2026-10-24T10:00:00+00:00"


def test_mcp_snapshot_metadata_does_not_relabel_other_provider_failures():
    runtime = SimpleNamespace(inventory=SimpleNamespace(inventory=SimpleNamespace(snapshot_meta={
        "data_source": "local_snapshot", "as_of": "2026-10-24T10:00:00+00:00",
    })))
    payload = {"ok": False, "error": {"code": "PROVIDER_UNAVAILABLE"}, "meta": {"data_source": "local_seed"}}

    result = mcp_server._preserve_snapshot_failure_metadata(payload, runtime)

    assert result["meta"]["data_source"] == "local_seed"
