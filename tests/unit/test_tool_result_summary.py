import json

from backend.app.agent.graph import _tool_result_summary


def test_large_tool_summary_remains_complete_json_for_auditable_facts():
    result = {
        "lines": [{"part_id": "P001", "warehouse_id": "W01", "shortage": 55,
                   "unit": "套", "note": "x" * 2200}],
        "source_refs": [{"entity": "inventory", "id": "I001"}],
    }

    serialized = _tool_result_summary(result)

    assert len(serialized) > 1500
    assert json.loads(serialized) == result
