from backend.app.agent.evidence import collect_evidence
from backend.app.agent.review import deterministic_review, combine_reviews
from backend.app.contracts.workflow import ReviewResult
from backend.app.ports.tools import ToolResult


def _state(answer="P001/W01 缺口55件，总额660.00元。", **overrides):
    result = ToolResult(ok=True, data={
        "lines": [{
            "part_id": "P001", "warehouse_id": "W01", "inventory_id": "I001",
            "shortage": 55, "quantity": 55, "unit": "套", "total_cents": 66000,
        }],
        "source_refs": [{"entity": "inventory", "id": "I001"}],
    }, meta={"data_source": "local_seed", "as_of": "2026-10-24T00:00:00Z"}, call_id="call-preview")
    state = {
        "task_type": "inventory",
        "final_answer": answer,
        "evidence": collect_evidence("replenishment_preview", result, call_id="call-preview"),
        "evidence_refs": [],
        "plan": [],
        "revision_count": 0,
    }
    state.update(overrides)
    return state


def test_numeric_mismatch_is_a_hard_deterministic_failure_with_fact_reason():
    result = deterministic_review(_state("P001/W01 缺口55套，总额650.00元。"))

    assert not result.passed
    check = next(item for item in result.checks if item.check_id == "NUMERIC_MATCH")
    assert not check.passed
    assert "650.00" in check.reason
    assert check.evidence_refs == ["call-preview/I001"]
    assert combine_reviews(result, ReviewResult(passed=True)).passed is False


def test_numeric_claim_without_a_real_source_reference_fails_source_check():
    state = _state()
    state["evidence"] = [item for item in state["evidence"] if not item.get("id")]
    result = deterministic_review(state)

    assert not result.passed
    check = next(item for item in result.checks if item.check_id == "SOURCE_EXISTS")
    assert not check.passed
    assert "source" in check.reason.lower()


def test_done_plan_step_requires_a_source_in_the_tool_fact_set():
    result = deterministic_review(_state(plan=[{
        "id": "read", "title": "读取库存", "status": "done",
        "evidence_refs": [{"call_id": "invented", "entity": "inventory", "id": "I999"}],
    }]))

    assert not result.passed
    assert any(item.check_id == "PLAN_EVIDENCE" and not item.passed for item in result.checks)


def test_required_plan_step_cannot_be_reviewed_as_done_until_tool_evidence_exists():
    result = deterministic_review(_state(plan=[{
        "id": "read", "title": "读取库存", "status": "pending",
        "required_action": "inventory_page",
    }]))

    assert not result.passed
    assert not next(item for item in result.checks if item.check_id == "PLAN_COMPLETE").passed


def test_completed_order_requires_verified_order_operation_and_consumed_approval():
    state = _state(
        "已创建订单 PO-1。",
        task_type="order",
        last_mutation_result={"operation_id": "op-1", "order_id": "PO-1"},
        order_verification={
            "order": {"id": "PO-1", "operation_id": "op-1"},
            "operation": {"id": "op-1", "status": "succeeded", "order_id": "PO-1"},
            "approval": {"state": "consumed", "operation_id": "op-1"},
        },
    )
    result = deterministic_review(state)
    assert result.passed
    assert next(item for item in result.checks if item.check_id == "ORDER_EXISTS").passed
    assert next(item for item in result.checks if item.check_id == "APPROVAL_EXISTS").passed

    state["order_verification"]["approval"]["state"] = "pending"
    rejected = deterministic_review(state)
    assert not rejected.passed
    assert not next(item for item in rejected.checks if item.check_id == "APPROVAL_EXISTS").passed


def test_same_part_shortage_must_be_cited_for_each_requested_warehouse():
    facts = []
    query_evidence = []
    for warehouse, call, inventory_id, shortage in (("W01", "c1", "I001", 55), ("W02", "c2", "I002", 20)):
        result = ToolResult(ok=True, data={"records": [{"id": inventory_id, "part_id": "P001",
            "warehouse_id": warehouse, "shortage": shortage, "unit": "套"}], "total": 1,
            "page": 1, "pages": 1}, meta={"data_source": "local_seed", "as_of": "2026-10-25T10:00:00Z"}, call_id=call)
        facts.extend(collect_evidence("inventory_page", result, call_id=call,
                                      arguments={"warehouse_id": warehouse, "part_ids": ["P001"]}))
        query_evidence.append({"call_id": call, "tool_name": "inventory_page", "data_source": "local_seed",
            "arguments": {"warehouse_id": warehouse, "part_ids": ["P001"]}, "as_of": "2026-10-25T10:00:00Z",
            "total": 1, "page": 1, "pages": 1, "record_ids": [inventory_id]})
    state = _state("W01的P001缺口55套。", task_type="inventory", evidence=facts,
        request_constraints={"warehouse_ids": ["W01", "W02"], "part_ids": ["P001"], "intent": "target_replenishment"},
        plan=[{"id": "read", "title": "库存", "status": "done", "required_action": "inventory_page",
               "query_evidence": query_evidence,
               "evidence_refs": [{"call_id": "c1", "entity": "inventory", "id": "I001"},
                                 {"call_id": "c2", "entity": "inventory", "id": "I002"}]}])
    result = deterministic_review(state)
    assert not result.passed
    assert any("W02/P001" in check.reason for check in result.checks)
