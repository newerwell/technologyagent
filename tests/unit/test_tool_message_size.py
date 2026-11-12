"""Model tool messages keep raw business facts without duplicating review indexes."""

import copy
import importlib
import json

import pytest

from backend.app.agent.evidence import collect_evidence
from backend.app.contracts.agent import ModelToolCall
from backend.app.ports.tools import ToolResult


@pytest.mark.parametrize("module", [
    "backend.app.agent.graph",
    "backend.app.agent.versions.v1_impl",
    "backend.app.agent.versions.v2_impl",
])
def test_inventory_tool_context_does_not_duplicate_internal_review_facts(module):
    data = {
        "records": [{"id": f"I{i:03}", "part_id": f"P{i:03}", "warehouse_id": "W01",
                     "unit": "套", "on_hand": 20, "safety_stock": 10, "warning": False,
                     "reserved": None, "inbound": None, "target_stock": None, "shortage": None,
                     "missing_fields": ["reserved", "inbound", "target_stock"]}
                    for i in range(1, 73)],
        "total": 72, "page": 1, "page_size": 100, "pages": 1,
        "source_refs": [{"entity": "inventory_snapshot", "id": "synthetic-snapshot",
                         "data_source": "local_snapshot", "as_of": "2026-01-01T00:00:00Z"}],
    }
    meta = {"data_source": "local_snapshot", "as_of": "2026-01-01T00:00:00Z",
            "snapshot_id": "synthetic-snapshot", "completeness": "unknown", "read_only": True,
            "dataset_id": "ds_test", "tool_name": "inventory_page",
            "query_evidence": {"page": 1, "pages": 1, "total": 72}}
    base = ToolResult(ok=True, data=data, meta=meta, call_id="call-inventory")
    evidence = collect_evidence("inventory_page", base, call_id=base.call_id)
    meta = {**meta, "evidence_refs": evidence}
    result = ToolResult(ok=True, data=data, meta=meta, call_id=base.call_id)
    original = copy.deepcopy(result)
    state = {"messages": []}
    call = ModelToolCall(id=base.call_id, name="inventory_page", arguments="{}")

    importlib.import_module(module)._append_tool_message(state, call, result)

    message = state["messages"][0]
    raw_bytes = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    assert len(message.content.encode("utf-8")) <= raw_bytes + 4096
    decoded = json.loads(message.content)
    assert decoded["data"] == data
    assert decoded["meta"] == {key: value for key, value in meta.items() if key != "evidence_refs"}
    assert message.tool_call_id == call.id and message.name == call.name
    assert result == original
    assert result.meta["evidence_refs"] == evidence


@pytest.mark.parametrize("module", [
    "backend.app.agent.graph",
    "backend.app.agent.versions.v1_impl",
    "backend.app.agent.versions.v2_impl",
])
def test_tool_error_and_source_metadata_remain_available_to_model(module):
    state = {"messages": []}
    call = ModelToolCall(id="call-error", name="replenishment_preview", arguments="{}")
    error = {"code": "UNSUPPORTED_OPERATION", "message": "snapshot target stock is unknown", "retryable": False}
    result = ToolResult(ok=False, error=error,
                        meta={"data_source": "local_snapshot", "snapshot_id": "snapshot-1",
                              "as_of": "2026-01-01T00:00:00Z"}, call_id=call.id)
    importlib.import_module(module)._append_tool_message(state, call, result)
    payload = json.loads(state["messages"][0].content)
    assert payload["ok"] is False and payload["error"] == error
    assert payload["meta"] == result.meta
