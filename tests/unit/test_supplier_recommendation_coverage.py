"""N04：推荐覆盖必须由已核验的报价关联证明，而不是全文出现S01/5天。

对应批次 20261109T132629Z-01573fa3ae 的 P03 第2题（F11 0/3）。
"""

from backend.app.agent.evidence import collect_evidence
from backend.app.agent.review import deterministic_review
from backend.app.contracts.workflow import QueryEvidence
from backend.app.ports.tools import ToolResult


def _preview(*, recommended="Q01", lines=None):
    default_lines = [
        {
            "inventory_id": "I001", "part_id": "P001", "warehouse_id": "W01", "unit": "套",
            "shortage": 55, "quantity": 55, "total_cents": 66000,
            "recommended_quote_id": recommended,
            "candidate_quotes": [
                {"quote_id": "Q01", "supplier_id": "S01", "lead_days": 5,
                 "unit_price_cents": 1200, "min_order_qty": 10},
                {"quote_id": "Q02", "supplier_id": "S02", "lead_days": 5,
                 "unit_price_cents": 1100, "min_order_qty": 1},
            ],
        },
    ]
    result = ToolResult(ok=True, data={
        "lines": lines if lines is not None else default_lines,
        "source_refs": [{"entity": "inventory", "id": "I001"}],
    }, meta={"data_source": "local_seed", "as_of": "2026-11-09T13:28:00Z"}, call_id="call-preview")
    return collect_evidence("replenishment_preview", result, call_id="call-preview", arguments={
        "part_ids": ["P001", "P002"], "warehouse_id": "W01", "max_lead_days": 7,
    })


def _state(answer, *, evidence=None):
    query = QueryEvidence(
        call_id="call-preview", tool_name="replenishment_preview", data_source="local_seed",
        arguments={"part_ids": ["P001", "P002"], "warehouse_id": "W01", "max_lead_days": 7},
        as_of="2026-11-09T13:28:00Z", total=2, page=1, pages=1, page_size=50,
        record_ids=["I001", "I002"],
    )
    return {
        "task_type": "general",
        "final_answer": answer,
        "evidence": evidence if evidence is not None else _preview(),
        "plan": [{"id": "search", "title": "查询", "status": "done",
                  "evidence_refs": [{"call_id": "call-preview", "entity": "inventory", "id": "I001"}],
                  "query_evidence": [query.model_dump(mode="json")]}],
        "request_constraints": {
            "intent": "supplier_recommendation", "warehouse_ids": ["W01"],
            "part_ids": ["P001"], "max_lead_days": 7,
        },
        "revision_count": 0,
    }


def _coverage(state):
    result = deterministic_review(state)
    check = next(item for item in result.checks if item.check_id == "SUPPLIER_RECOMMENDATION_COVERAGE")
    return check.passed, check.reason


def test_quote_only_answer_is_resolved_through_the_service_selection():
    passed, reason = _coverage(_state("推荐报价 Q01：交期5天，满足7天上限。"))

    assert passed, reason


def test_table_entity_columns_and_lead_column_cover():
    passed, reason = _coverage(_state(
        "推荐报价如下：\n| 实体 | 报价 | 交期 |\n|---|---|---|\n| P001/W01 | Q01 | 5天 |"
    ))

    assert passed, reason


def test_supplier_and_part_scope_binds_the_service_selected_quote():
    passed, reason = _coverage(_state("推荐华东制动（P001/W01/S01）：交期5天，满足7天上限。"))

    assert passed, reason


def test_lead_time_without_bindable_entity_does_not_cover():
    passed, reason = _coverage(_state("推荐华东制动，交期5天，满足7天上限。"))

    assert not passed
    assert "lead time" in reason


def test_lead_time_borrowed_from_another_quote_does_not_cover():
    passed, reason = _coverage(_state("推荐报价 Q02：交期5天，满足7天上限。"))

    assert not passed
    assert "lead time" in reason


def test_other_supplier_cannot_cover_the_selected_quote():
    passed, reason = _coverage(_state("推荐报价 Q01（P001/W01/S02）：交期5天。"))

    assert not passed


def test_request_ceiling_is_not_a_quote_lead_time():
    passed, reason = _coverage(_state("推荐报价 Q01：交期7天，满足7天上限。"))

    assert not passed


def test_recommendation_without_lead_time_does_not_cover():
    passed, reason = _coverage(_state("推荐华东制动，P001/W01/S01 报价 Q01。"))

    assert not passed
    assert "lead time" in reason


def test_same_value_for_another_part_does_not_cover():
    evidence = _preview(lines=[
        {
            "inventory_id": "I001", "part_id": "P001", "warehouse_id": "W01", "unit": "套",
            "shortage": 55, "quantity": 55, "total_cents": 66000, "recommended_quote_id": "Q01",
            "candidate_quotes": [{"quote_id": "Q01", "supplier_id": "S01", "lead_days": 5,
                                  "unit_price_cents": 1200, "min_order_qty": 10}],
        },
        {
            "inventory_id": "I002", "part_id": "P002", "warehouse_id": "W02", "unit": "个",
            "shortage": 0, "quantity": 0, "total_cents": 0, "recommended_quote_id": "Q04",
            "candidate_quotes": [{"quote_id": "Q04", "supplier_id": "S04", "lead_days": 5,
                                  "unit_price_cents": 800, "min_order_qty": 1}],
        },
    ])

    passed, reason = _coverage(_state(
        "推荐报价 Q01 交期5天；P002/W02/S04/Q04 交期5天。", evidence=evidence
    ))
    assert passed, reason

    borrowed = _coverage(_state("推荐报价 Q01 交期5天。", evidence=evidence))
    assert not borrowed[0]
