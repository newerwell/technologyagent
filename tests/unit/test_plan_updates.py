from backend.app.agent.harness import build_plan, classify_task, sanitize_plan, skip_pending, update_plan_from_result
from backend.app.agent.review import deterministic_review
from backend.app.contracts.workflow import PlanItem
from backend.app.ports.tools import ToolResult


def test_run_budget_subtracts_persisted_active_time_across_resume():
    from backend.app.agent.budget import RunBudget

    clock = [100.0]
    budget = RunBudget("run", max_active_seconds=180.0,
                       initial_active_seconds=175.0, monotonic=lambda: clock[0])
    assert budget.remaining_seconds == 5.0
    clock[0] += 5.0
    assert budget.remaining_seconds == 0.0


def test_structured_plan_has_unique_ids_and_server_owned_pending_statuses():
    plan = build_plan("order")

    assert len({item.id for item in plan}) == len(plan)
    assert plan
    assert all(item.status == "pending" for item in plan)
    assert all(item.required_action != "order_create" for item in plan)


def test_negated_order_terms_do_not_turn_inventory_questions_into_order_tasks():
    assert classify_task(
        "只查P001在W01缺货件数，不要给采购建议，也不要下单。"
    ) == "inventory"


def test_negated_supplier_terms_do_not_turn_inventory_questions_into_supplier_tasks():
    assert classify_task("查询P001库存，不要给供应商和报价建议。") == "inventory"


def test_replenishment_query_stays_readonly_and_inventory_warning_has_a_plan_step():
    assert classify_task("哪些零件要补货？只看W01。") == "inventory"
    plan = build_plan("inventory")
    assert "inventory_warning" in (plan[0].required_action or "")


def test_failed_plan_step_can_complete_after_a_successful_retry():
    plan = [PlanItem(id="read", title="读取库存", required_action="inventory_page")]
    failed = update_plan_from_result(plan, ToolResult(
        ok=False, error={"code": "TOOL_FAILED"}, call_id="call-failed",
        meta={"tool_name": "inventory_page"},
    ))
    retried = update_plan_from_result(failed, ToolResult(
        ok=True, data={"records": [{"id": "I001"}], "total": 1}, call_id="call-retry",
        meta={"tool_name": "inventory_page", "evidence_refs": [{
            "call_id": "call-retry", "entity": "inventory", "id": "I001",
        }]},
    ))

    assert failed[0].status == "failed"
    assert retried[0].status == "done"


def test_empty_successful_query_completes_with_query_evidence_without_fake_entity_ref():
    plan = [PlanItem(id="read", title="查询库存", required_action="inventory_page")]
    result = ToolResult(
        ok=True, data={"records": [], "total": 0}, call_id="call-empty",
        meta={"tool_name": "inventory_page", "query_evidence": {
            "call_id": "call-empty", "tool_name": "inventory_page",
            "data_source": "local_seed", "arguments": {"warehouse_id": "W99"},
            "as_of": "2026-10-24T00:00:00Z", "total": 0,
        }},
    )

    updated = update_plan_from_result(plan, result)

    assert updated[0].status == "done"
    assert updated[0].evidence_refs == []
    assert updated[0].query_evidence[0].total == 0
    review = deterministic_review({
        "task_type": "inventory",
        "final_answer": "W99 当前页没有库存记录。",
        "plan": [item.model_dump(mode="json") for item in updated],
        "evidence": [],
    })
    assert review.passed


def test_only_successful_tool_result_with_evidence_marks_matching_step_done():
    plan = [
        PlanItem(id="read", title="读取库存", required_action="inventory_page"),
        PlanItem(id="quotes", title="核对报价", required_action="quote_list"),
    ]
    result = ToolResult(
        ok=True,
        data={"records": [{"id": "I001"}]},
        call_id="call-inventory",
        meta={"tool_name": "inventory_page", "evidence_refs": [{"call_id": "call-inventory", "entity": "inventory", "id": "I001"}]},
    )

    updated = update_plan_from_result(plan, result)

    assert updated[0].status == "done"
    assert updated[0].evidence_refs[0].id == "I001"
    assert updated[1].status == "pending"


def test_failed_or_unmatched_tool_cannot_mark_step_done():
    plan = [PlanItem(id="read", title="读取库存", required_action="inventory_page")]
    failed = update_plan_from_result(plan, ToolResult(
        ok=False, error={"code": "TOOL_FAILED"}, call_id="call-failed",
        meta={"tool_name": "inventory_page"},
    ))
    unmatched = update_plan_from_result(plan, ToolResult(
        ok=True, data={"records": [{"id": "I001"}]}, call_id="call-other",
        meta={"tool_name": "supplier_query", "evidence_refs": [{"call_id": "call-other", "entity": "supplier", "id": "S01"}]},
    ))

    assert failed[0].status == "failed"
    assert unmatched[0].status == "pending"


def test_cancel_skips_every_unfinished_step_and_model_status_is_ignored():
    plan = [
        PlanItem(id="write", title="创建订单", status="done", required_action="order_create"),
        PlanItem(id="read", title="核对结果", required_action="order_result_read"),
    ]

    safe = sanitize_plan(plan)
    skipped = skip_pending(safe)
    assert safe[0].status == "pending"
    assert skipped[0].status == "skipped"
    assert skipped[1].status == "skipped"
