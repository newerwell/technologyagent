from backend.app.agent.evidence import collect_evidence, validate_business_claims
from backend.app.ports.tools import ToolResult


def _quote_evidence():
    result = ToolResult(ok=True, data={
        "lines": [
            {"part_id": "P001", "warehouse_id": "W01", "shortage": 55,
             "candidate_quotes": [{"quote_id": "Q01", "supplier_id": "S01",
                                   "unit_price_cents": 1200, "lead_days": 5,
                                   "quantity": 55, "line_total_cents": 66000}]},
            {"part_id": "P002", "warehouse_id": "W02", "shortage": 36,
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
