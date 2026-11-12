"""An honestly unknown target gap may complete only after the requested pages."""

import copy

from backend.app.agent.evidence import collect_evidence
from backend.app.agent.harness import extract_request_constraints
from backend.app.agent.review import deterministic_review
from backend.app.ports.tools import ToolResult


def _state():
    evidence, queries = [], []
    for page in (1, 2):
        result = ToolResult(ok=True, call_id=f"page-{page}",
                            meta={"data_source": "local_snapshot", "as_of": "2026-01-01T00:00:00Z"},
                            data={"records": [{"id": f"I{page}", "part_id": f"P{page:03}",
                                               "warehouse_id": "W01", "unit": "套", "on_hand": 20,
                                               "safety_stock": 5, "target_stock": None, "shortage": None,
                                               "missing_fields": ["reserved", "inbound", "target_stock"]}],
                                  "total": 2, "pages": 2, "page": page, "page_size": 1,
                                  "source_refs": [{"entity": "inventory_snapshot", "id": "snapshot",
                                                   "data_source": "local_snapshot", "as_of": "2026-01-01T00:00:00Z"}]})
        evidence.extend(collect_evidence("inventory_page", result, call_id=result.call_id,
                                         arguments={"page": page, "page_size": 1}))
        queries.append({"call_id": result.call_id, "tool_name": "inventory_page",
                        "data_source": "local_snapshot", "as_of": "2026-01-01T00:00:00Z",
                        "arguments": {"page": page, "page_size": 1}, "total": 2, "pages": 2,
                        "page": page, "page_size": 1, "record_ids": [f"I{page}"]})
    refs = [item for item in evidence if "field" not in item]
    return {"task_type": "inventory", "original_request": "哪些零件要补货",
            "request_constraints": extract_request_constraints("哪些零件要补货"),
            "final_answer": "已读取当前保存的库存快照；目标库存、预留和在途字段未知，无法确定目标补货清单。需要补齐这些业务数据，不能把未知缺口当作没有缺口。",
            "evidence": evidence,
            "plan": [{"id": "read_inventory", "required": True, "status": "done",
                      "evidence_refs": refs, "query_evidence": queries}]}


def test_complete_snapshot_can_explain_unknown_target_gap_without_fabricating_values():
    review = deterministic_review(_state())
    assert review.passed, [(item.check_id, item.reason) for item in review.checks if not item.passed]


def test_unknown_target_gap_does_not_excuse_missing_page_or_invented_zero():
    state = _state()
    partial = copy.deepcopy(state)
    partial["plan"][0]["query_evidence"].pop()
    assert not deterministic_review(partial).passed
    state["final_answer"] = "P001/W01目标缺口0套。"
    assert not deterministic_review(state).passed
