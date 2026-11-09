from backend.app.agent.evidence import validate_business_claims
from backend.app.agent.fact_checks import extract_business_claims


def _fact(field, value, unit, *, entity="inventory", entity_id, part_id=None,
          warehouse_id=None, supplier_id=None):
    return {
        "call_id": f"{entity_id}-{field}",
        "entity": entity,
        "id": entity_id,
        "field": field,
        "value": value,
        "unit": unit,
        "part_id": part_id,
        "warehouse_id": warehouse_id,
        "supplier_id": supplier_id,
        "source_refs": [{"call_id": f"{entity_id}-{field}", "entity": entity, "id": entity_id}],
    }


def _facts():
    return [
        _fact("shortage", 55, "套", entity_id="I001", part_id="P001", warehouse_id="W01"),
        _fact("quantity", 55, "套", entity="replenishment", entity_id="I001", part_id="P001", warehouse_id="W01"),
        _fact("warning_count", 1, "count", entity_id="I001", part_id="P001", warehouse_id="W01"),
        _fact("shortage", 10, "条", entity_id="I004", part_id="P004", warehouse_id="W01"),
        _fact("lead_days", 5, "days", entity="quote", entity_id="Q01", part_id="P001", supplier_id="S01"),
        _fact("max_lead_days", 7, "days", entity="request_constraint", entity_id="request-1", part_id="P001"),
        _fact("unit_price_cents", 1100, "cents", entity="quote", entity_id="Q02", part_id="P002",
              warehouse_id="W02", supplier_id="S02"),
    ]


def _claim(answer, number):
    claims, violations = extract_business_claims(answer)
    assert not violations
    matches = [claim for claim in claims if claim.number == str(number)]
    assert len(matches) == 1
    return matches[0]


def test_warning_label_does_not_change_shortage_field():
    answer = "预警：P001/W01缺口55套。"
    claim = _claim(answer, 55)
    assert claim.fields == frozenset({"shortage"})
    assert claim.scope == frozenset({"P001", "W01"})
    assert validate_business_claims(answer, _facts()).passed


def test_table_column_beats_warning_in_other_cell():
    answer = "| 零件 | 仓库 | 预警 | 缺口 |\n| --- | --- | --- | ---: |\n| P001 | W01 | 有预警 | 55套 |"
    claim = _claim(answer, 55)
    assert claim.fields == frozenset({"shortage"})
    assert claim.scope == frozenset({"P001", "W01"})
    assert validate_business_claims(answer, _facts()).passed


def test_purchase_quantity_is_not_delivery_limit():
    answer = "P001/W01要求采购数量55套。"
    claim = _claim(answer, 55)
    assert claim.fields == frozenset({"quantity"})
    assert validate_business_claims(answer, _facts()).passed


def test_deadline_and_quote_lead_are_separate_lines():
    answer = "P001要求7天内到货\nP001/S01交期5天。"
    claims, violations = extract_business_claims(answer)
    assert not violations
    by_number = {claim.number: claim for claim in claims}
    assert by_number["7"].fields == frozenset({"max_lead_days"})
    assert by_number["7"].scope == frozenset({"P001"})
    assert by_number["5"].fields == frozenset({"lead_days"})
    assert by_number["5"].scope == frozenset({"P001", "S01"})
    assert validate_business_claims(answer, _facts()).passed


def test_adjacent_part_lines_keep_separate_scope():
    answer = "P001/W01缺口55套\nP004/W01缺口10条。"
    claims, violations = extract_business_claims(answer)
    assert not violations
    by_number = {claim.number: claim for claim in claims}
    assert by_number["55"].scope == frozenset({"P001", "W01"})
    assert by_number["10"].scope == frozenset({"P004", "W01"})
    assert all(claim.fields == frozenset({"shortage"}) for claim in claims)
    assert validate_business_claims(answer, _facts()).passed


def test_explicit_entity_heading_can_scope_next_line():
    answer = "P002/W02/S02：\n单价11元"
    claim = _claim(answer, 11)
    assert claim.fields == frozenset({"unit_price_cents"})
    assert claim.scope == frozenset({"P002", "W02", "S02"})
    assert validate_business_claims(answer, _facts()).passed


def test_wrong_table_cell_value_and_unit_still_fail():
    evidence = _facts()
    assert not validate_business_claims("P001/W01缺口56套。", evidence).passed
    assert not validate_business_claims("P001/W01缺口55件。", evidence).passed
    assert not validate_business_claims("P004/W01缺口55套。", evidence).passed


def test_ambiguous_entity_scope_does_not_guess():
    evidence = _facts() + [
        _fact("shortage", 55, "套", entity_id="I005", part_id="P005", warehouse_id="W02"),
    ]
    checked = validate_business_claims("缺口55套。", evidence)
    assert not checked.passed
    assert any("AMBIGUOUS" in issue for issue in checked.violations)


def test_two_part_claims_on_one_line_keep_independent_scope():
    answer = "P001/W01缺口55套，P004/W01缺口10条。"
    claims, violations = extract_business_claims(answer)
    assert not violations
    assert {claim.number: claim.scope for claim in claims} == {
        "55": frozenset({"P001", "W01"}),
        "10": frozenset({"P004", "W01"}),
    }
    assert validate_business_claims(answer, _facts()).passed
