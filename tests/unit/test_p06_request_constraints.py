from backend.app.agent.harness import classify_task, extract_request_constraints, update_plan_from_result
from backend.app.agent.review import deterministic_review
from backend.app.contracts.workflow import PlanItem
from backend.app.ports.tools import ToolResult


def test_request_constraints_keep_warehouse_parts_and_lead_limit_as_user_scope():
    constraints = extract_request_constraints("推荐P001在W01七天内到货的供应商")

    assert constraints["warehouse_ids"] == ["W01"]
    assert constraints["part_ids"] == ["P001"]
    assert constraints["max_lead_days"] == 7
    assert constraints["intent"] == "supplier_recommendation"


def test_seven_day_supplier_recommendation_gets_a_persisted_supplier_plan():
    request = "刹车片要求7天内到货，推荐哪家？"
    assert classify_task(request) == "supplier"


def test_cheapest_supplier_question_gets_a_persisted_quote_plan_without_a_lead_filter():
    assert classify_task("P003买哪家的最便宜？") == "supplier"


def test_seven_day_recommendation_needs_server_filtered_preview_query():
    state = {
        "task_type": "supplier",
        "request_constraints": extract_request_constraints("推荐P001在W01七天内到货的供应商"),
        "final_answer": "推荐S01，交期5天。",
        "plan": [PlanItem(id="read", title="读取报价", status="done", required_action="quote_list",
                          query_evidence=[{"call_id": "q", "tool_name": "quote_list", "data_source": "local_seed",
                                           "arguments": {"part_id": "P001", "warehouse_id": "W01"}}]).model_dump(mode="json")],
        "evidence": [
            {"call_id": "q", "entity": "quote", "id": "Q01", "field": "supplier_id", "value": "S01",
             "part_id": "P001", "warehouse_id": "W01", "supplier_id": "S01"},
        ],
    }

    checked = deterministic_review(state)

    assert not checked.passed
    assert any(item.check_id == "REQUEST_CONSTRAINTS" and not item.passed for item in checked.checks)


def test_target_gap_review_requires_complete_entity_and_positive_gap_coverage():
    constraints = extract_request_constraints("W01哪些零件需要补货？")
    plan = PlanItem(id="read", title="读取库存", status="done", required_action="inventory_page",
                    query_evidence=[{"call_id": "i", "tool_name": "inventory_page", "data_source": "local_seed",
                                     "arguments": {"warehouse_id": "W01", "page": 1, "page_size": 50},
                                     "total": 3, "page": 1, "pages": 1,
                                     "record_ids": ["I001", "I003", "I004"]}]).model_dump(mode="json")
    state = {
        "task_type": "inventory", "request_constraints": constraints,
        "final_answer": "P001/W01缺口55件；P003/W01缺口36件。",
        "plan": [plan],
        "evidence": [
            {"call_id": "i", "entity": "inventory", "id": "I001", "field": "shortage", "value": 55,
             "unit": "count", "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "i", "entity": "inventory", "id": "I003", "field": "shortage", "value": 36,
             "unit": "count", "part_id": "P003", "warehouse_id": "W01"},
            {"call_id": "i", "entity": "inventory", "id": "I004", "field": "shortage", "value": 10,
             "unit": "count", "part_id": "P004", "warehouse_id": "W01"},
        ],
    }

    checked = deterministic_review(state)

    assert not checked.passed
    assert any(item.check_id == "TARGET_GAP_COVERAGE" and not item.passed for item in checked.checks)


def test_target_gap_and_inventory_warning_are_distinct_query_intents():
    assert extract_request_constraints("W01库存预警有哪些？")["intent"] == "inventory_warning"
    assert extract_request_constraints("W01哪些零件需要补货？")["intent"] == "target_replenishment"


def test_single_part_shortage_question_does_not_expand_to_all_warehouse_gaps():
    constraints = extract_request_constraints("P001当前目标库存缺口是多少套？")
    assert constraints["part_ids"] == ["P001"]
    assert constraints["intent"] == "single_part_shortage"


def test_quote_list_cannot_complete_a_seven_day_recommendation_step():
    plan = [PlanItem(id="read_supplier", title="查推荐供应商", required_action="quote_list,replenishment_preview")]
    constraints = extract_request_constraints("推荐P001在W01七天内到货的供应商")
    quote_only = ToolResult(ok=True, data={"records": [{"id": "Q01"}], "total": 1}, call_id="q", meta={
        "tool_name": "quote_list", "evidence_refs": [{"call_id": "q", "entity": "quote", "id": "Q01"}],
        "query_evidence": {"call_id": "q", "tool_name": "quote_list", "data_source": "local_seed",
                           "arguments": {"part_id": "P001", "warehouse_id": "W01"}, "total": 1},
    })

    updated = update_plan_from_result(plan, quote_only, constraints)

    assert updated[0].status == "running"


def test_target_gap_plan_requires_all_server_pages_before_done():
    plan = [PlanItem(id="read_inventory", title="读取目标缺口", required_action="inventory_page")]
    constraints = extract_request_constraints("W01哪些零件需要补货？")
    def page_result(call_id, page, record_id):
        return ToolResult(ok=True, data={"records": [{"id": record_id}], "total": 2, "page": page,
                           "pages": 2, "page_size": 1}, call_id=call_id, meta={
            "tool_name": "inventory_page", "evidence_refs": [{"call_id": call_id, "entity": "inventory", "id": record_id}],
            "query_evidence": {"call_id": call_id, "tool_name": "inventory_page", "data_source": "local_seed",
                               "arguments": {"warehouse_id": "W01", "page": page, "page_size": 1},
                               "total": 2, "page": page, "pages": 2, "page_size": 1,
                               "record_ids": [record_id]},
        })
    first = update_plan_from_result(plan, page_result("i1", 1, "I001"), constraints)
    second = update_plan_from_result(first, page_result("i2", 2, "I003"), constraints)

    assert first[0].status == "running"
    assert second[0].status == "done"
    assert len(second[0].query_evidence) == 2
