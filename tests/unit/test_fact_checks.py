from backend.app.agent.evidence import collect_evidence, validate_business_claims
from backend.app.ports.tools import ToolResult


def _quote_evidence():
    result = ToolResult(ok=True, data={
        "lines": [
            {"part_id": "P001", "warehouse_id": "W01", "unit": "套", "shortage": 55,
             "candidate_quotes": [{"quote_id": "Q01", "supplier_id": "S01",
                                   "unit_price_cents": 1200, "lead_days": 5,
                                   "quantity": 55, "line_total_cents": 66000}]},
            {"part_id": "P002", "warehouse_id": "W02", "unit": "个", "shortage": 36,
             "candidate_quotes": [{"quote_id": "Q02", "supplier_id": "S02",
                                   "unit_price_cents": 1100, "lead_days": 12,
                                   "quantity": 55, "line_total_cents": 60500}]},
        ],
        "source_refs": [
            {"entity": "inventory", "id": "I001"},
            {"entity": "inventory", "id": "I002"},
        ],
    }, call_id="quote-preview")
    return collect_evidence("replenishment_preview", result, call_id="quote-preview")


def test_money_claims_remain_bound_to_the_matching_part_supplier_and_column():
    evidence = _quote_evidence()
    table = (
        "| 零件 | 仓库 | 供应商 | 单价 | 行金额 |\n"
        "| --- | --- | --- | ---: | ---: |\n"
        "| P001 | W01 | S01 | 12元 | 660元 |\n"
        "| P002 | W02 | S02 | 11元 | 605元 |"
    )

    assert validate_business_claims(table, evidence).passed
    assert not validate_business_claims("P002/W02/S02单价12元。", evidence).passed
    assert not validate_business_claims("P001/W01/S01单价12.001元。", evidence).passed


def test_unscoped_equal_prices_are_reported_as_ambiguous():
    result = ToolResult(ok=True, data={"records": [
        {"id": "Q01", "part_id": "P001", "warehouse_id": "W01", "supplier_id": "S01", "unit_price_cents": 1200},
        {"id": "Q02", "part_id": "P002", "warehouse_id": "W02", "supplier_id": "S02", "unit_price_cents": 1200},
    ], "total": 2}, call_id="quotes")
    evidence = collect_evidence("quote_list", result, call_id="quotes")

    checked = validate_business_claims("单价12元。", evidence)

    assert not checked.passed
    assert any("AMBIGUOUS" in item for item in checked.violations)


def test_non_finite_and_boolean_amounts_cannot_be_treated_as_missing_evidence():
    evidence = collect_evidence("quote_list", ToolResult(ok=True, data={"records": [
        {"id": "Q01", "part_id": "P001", "warehouse_id": "W01", "supplier_id": "S01",
         "unit_price_cents": 1200, "min_order_qty": True}
    ]}, call_id="quotes"), call_id="quotes")

    assert not validate_business_claims("P001/W01单价NaN元。", evidence).passed
    assert not validate_business_claims("P001/W01单价Infinity元。", evidence).passed
    assert not validate_business_claims("P001/W01起订量True件。", evidence).passed


def test_boolean_business_state_is_checked_against_its_typed_fact_not_as_a_number():
    evidence = collect_evidence("quote_list", ToolResult(ok=True, data={"records": [
        {"id": "Q06", "part_id": "P003", "supplier_id": "S03", "is_valid": False},
    ]}, call_id="quotes"), call_id="quotes")

    assert validate_business_claims("P003的有效报价状态为false。", evidence).passed
    assert not validate_business_claims("P003的有效报价状态为true。", evidence).passed


def test_entity_scope_survives_colon_and_newline_boundaries():
    evidence = _quote_evidence()
    assert not validate_business_claims("P002/W02/S02：单价12元。", evidence).passed
    assert not validate_business_claims("P002/W02/S02：\n单价12元。", evidence).passed
    assert validate_business_claims("P002/W02/S02：\n单价11元。", evidence).passed


def test_claim_must_match_latest_snapshot_even_if_old_value_exists():
    evidence = [
        {"call_id": "old", "entity": "inventory", "id": "I001", "field": "available",
         "value": 55, "unit": "件", "part_id": "P001", "warehouse_id": "W01", "as_of": "2026-10-24T10:00:00Z",
         "source_refs": [{"call_id": "old", "entity": "inventory", "id": "I001"}]},
        {"call_id": "new", "entity": "inventory", "id": "I001", "field": "available",
         "value": 50, "unit": "件", "part_id": "P001", "warehouse_id": "W01", "as_of": "2026-10-25T10:00:00+00:00",
         "source_refs": [{"call_id": "new", "entity": "inventory", "id": "I001"}]},
    ]
    assert not validate_business_claims("P001/W01可用库存55件。", evidence).passed
    assert validate_business_claims("P001/W01可用库存50件。", evidence).passed


def test_same_snapshot_conflicts_and_concrete_units_are_rejected():
    evidence = [
        {"call_id": "a", "entity": "inventory", "id": "I001", "field": "shortage",
         "value": 55, "unit": "套", "part_id": "P001", "warehouse_id": "W01", "as_of": "2026-10-25T10:00:00Z",
         "source_refs": [{"call_id": "a", "entity": "inventory", "id": "I001"}]},
        {"call_id": "b", "entity": "inventory", "id": "I001", "field": "shortage",
         "value": 50, "unit": "套", "part_id": "P001", "warehouse_id": "W01", "as_of": "2026-10-25T12:00:00+02:00",
         "source_refs": [{"call_id": "b", "entity": "inventory", "id": "I001"}]},
    ]
    assert not validate_business_claims("P001/W01缺口55套。", evidence).passed
    evidence.pop()
    assert not validate_business_claims("P001/W01缺口55台。", evidence).passed


def test_collected_business_unit_is_not_collapsed_to_generic_count():
    evidence = _quote_evidence()
    assert validate_business_claims("P001/W01目标缺口55套。", evidence).passed
    assert not validate_business_claims("P001/W01目标缺口55台。", evidence).passed


def test_concrete_pair_unit_is_accepted_but_other_units_stay_rejected():
    evidence = [{"call_id": "c", "entity": "inventory", "id": "I008", "field": "available",
        "value": 40, "unit": "对", "part_id": "P006", "warehouse_id": "W01",
        "source_refs": [{"call_id": "c", "entity": "inventory", "id": "I008"}]}]
    assert validate_business_claims("P006/W01可用库存40对。", evidence).passed
    assert not validate_business_claims("P006/W01可用库存40件。", evidence).passed


def test_exceeded_supplier_quote_is_compared_to_global_lead_time_ceiling():
    evidence = [
        {"call_id": "quote", "entity": "quote", "id": "Q02", "field": "lead_days",
         "value": 12, "unit": "days", "part_id": "P001", "warehouse_id": "W01",
         "supplier_id": "S02", "as_of": "2026-10-24T10:00:00Z"},
        {"call_id": "preview", "entity": "request_constraint", "field": "max_lead_days",
         "value": 7, "unit": "days", "part_id": "P001", "warehouse_id": "W01",
         "as_of": "2026-10-24T10:00:00Z"},
    ]

    assert validate_business_claims(
        "P001/W01/S02交期12天，超过7天上限。", evidence
    ).passed


def test_consistent_inventory_and_preview_observations_share_business_identity():
    inventory = collect_evidence("inventory_page", ToolResult(ok=True, data={"records": [
        {"id": "I001", "part_id": "P001", "warehouse_id": "W01", "shortage": 55, "unit": "套"},
    ]}, call_id="inventory"), call_id="inventory")
    preview = collect_evidence("replenishment_preview", ToolResult(ok=True, data={"lines": [
        {"inventory_id": "I001", "part_id": "P001", "warehouse_id": "W01", "shortage": 55, "unit": "套"},
    ]}, call_id="preview"), call_id="preview")
    claim = "W01的P001目标库存缺口为55套。"

    assert validate_business_claims(claim, inventory).passed
    assert validate_business_claims(claim, preview).passed
    assert validate_business_claims(claim, inventory + preview).passed


def test_cross_source_same_time_conflict_stays_ambiguous():
    inventory = collect_evidence("inventory_page", ToolResult(ok=True, data={"records": [
        {"id": "I001", "part_id": "P001", "warehouse_id": "W01", "shortage": 55, "unit": "套"},
    ]}, meta={"as_of": "2026-10-26T10:00:00Z"}, call_id="inventory"), call_id="inventory")
    preview = collect_evidence("replenishment_preview", ToolResult(ok=True, data={"lines": [
        {"inventory_id": "I001", "part_id": "P001", "warehouse_id": "W01", "shortage": 50, "unit": "套"},
    ]}, meta={"as_of": "2026-10-26T10:00:00+00:00"}, call_id="preview"), call_id="preview")

    checked = validate_business_claims("W01的P001目标库存缺口为55套。", inventory + preview)
    assert not checked.passed
    assert any("AMBIGUOUS" in issue for issue in checked.violations)
