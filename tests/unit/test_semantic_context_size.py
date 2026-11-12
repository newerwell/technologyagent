import copy
import json
import pytest
from backend.app.agent.budget import RunBudget
from backend.app.agent.evidence import collect_evidence
from backend.app.agent.review import semantic_review
from backend.app.contracts.agent import ModelDelta
from backend.app.contracts.common import RequestContext
from backend.app.ports.tools import ToolResult

class _Grader:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.messages = None

    async def stream(self, messages, tools, ctx):
        self.calls += 1
        self.messages = messages
        assert tools == []
        assert "private reasoning" in messages[0].content.lower()
        yield ModelDelta(kind="token", content=json.dumps(self.payload))


@pytest.mark.asyncio
async def test_semantic_review_deduplicates_source_lists_without_losing_fact_values():
    data = {"records": [{"id": f"I{i:03}", "part_id": f"P{i:03}", "warehouse_id": "W01",
                          "unit": "套", "on_hand": 20, "safety_stock": 5, "warning": False}
                         for i in range(1, 73)], "total": 72,
            "source_refs": [{"entity": "inventory_snapshot", "id": "synthetic-snapshot"}]}
    evidence = collect_evidence("inventory_page", ToolResult(
        ok=True, data=data, call_id="inventory", meta={"data_source": "local_snapshot"}),
        call_id="inventory")
    state = {"task_type": "inventory", "original_request": "库存分析", "final_answer": "已核查库存。",
             "evidence": evidence}
    original = copy.deepcopy(state)
    grader = _Grader({"passed": True, "issues": []})
    await semantic_review(state, grader, RunBudget("compact-review"),
                          RequestContext(owner_id="owner", request_id="request", run_id="compact-review"))
    content = grader.messages[1].content
    assert len(content.encode("utf-8")) < 500_000
    payload = json.loads(content)
    from backend.app.agent.review import _semantic_facts
    restored = []
    for fact in payload["verified_facts"]:
        restored_fact = dict(fact)
        group = restored_fact.pop("source_ref_group", None)
        if group is not None:
            restored_fact["source_refs"] = payload["source_ref_groups"][group]
        restored.append(restored_fact)
    assert restored == _semantic_facts(evidence)
    assert state == original
