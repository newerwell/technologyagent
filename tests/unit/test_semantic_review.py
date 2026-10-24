import json

import pytest

from backend.app.agent.budget import RunBudget, RunLimitExceeded
from backend.app.agent.review import combine_reviews, deterministic_review, semantic_review
from backend.app.contracts.agent import ModelDelta
from backend.app.contracts.common import RequestContext
from backend.app.contracts.workflow import ReviewResult


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
async def test_semantic_review_uses_rubric_and_shared_model_budget():
    grader = _Grader({"passed": True, "issues": []})
    budget = RunBudget("run-1", max_model_calls=2)
    context = RequestContext(owner_id="owner-1", request_id="request-1", run_id="run-1")

    result = await semantic_review({"task_type": "inventory", "final_answer": "库存分析已完成。"}, grader, budget, context)

    assert result.passed
    assert result.checks[0].check_id == "SEMANTIC_COMPLETE"
    assert grader.calls == 1
    assert budget.model_calls == 1


@pytest.mark.asyncio
async def test_semantic_review_receives_structured_facts_and_persisted_order_evidence():
    grader = _Grader({"passed": True, "issues": []})
    state = {
        "task_type": "order",
        "final_answer": "已提交 PO-123，55件，660元。",
        "evidence_refs": [{"call_id": "order_workflow", "entity": "orders", "id": "po-id"}],
        "evidence": [{"call_id": "order_workflow", "entity": "orders", "id": "po-id",
                      "field": "total_cents", "value": 66000, "unit": "cents",
                      "source_refs": [{"entity": "orders", "id": "po-id"}]}],
        "verified_orders": {"orders": [{
            "order": {"id": "po-id", "number": "PO-123", "status": "submitted", "total_cents": 66000,
                      "owner_id": "must-not-leak"},
            "operation": {"id": "op-id", "status": "succeeded", "order_id": "po-id"},
            "approval": {"id": "approval-id", "state": "consumed", "operation_id": "op-id"},
        }]},
    }

    await semantic_review(
        state, grader, RunBudget("run-evidence"),
        RequestContext(owner_id="owner", request_id="request", run_id="run-evidence"),
    )

    payload = json.loads(grader.messages[1].content)
    assert payload["verified_facts"][0]["value"] == 66000
    assert payload["order_verification"][0]["order"]["number"] == "PO-123"
    assert payload["order_verification"][0]["approval"]["state"] == "consumed"
    assert "owner_id" not in payload["order_verification"][0]["order"]


@pytest.mark.asyncio
async def test_semantic_review_does_not_run_after_shared_model_budget_is_exhausted():
    grader = _Grader({"passed": True, "issues": []})
    budget = RunBudget("run-1", max_model_calls=0)

    with pytest.raises(RunLimitExceeded):
        await semantic_review({"task_type": "inventory", "final_answer": "x"}, grader, budget,
                              RequestContext(owner_id="owner-1", request_id="request-1", run_id="run-1"))
    assert grader.calls == 0


@pytest.mark.asyncio
async def test_semantic_pass_cannot_override_deterministic_numeric_failure():
    from tests.unit.test_deterministic_review import _state

    hard = deterministic_review(_state("P001/W01 缺口55件，总额650.00元。"))
    semantic = await semantic_review(
        {"task_type": "inventory", "final_answer": "总额650元"},
        _Grader({"passed": True, "issues": []}),
        RunBudget("run-2"),
        RequestContext(owner_id="owner-1", request_id="request-2", run_id="run-2"),
    )

    combined = combine_reviews(hard, semantic)
    assert not combined.passed
    assert any(item.check_id == "NUMERIC_MATCH" and not item.passed for item in combined.checks)
