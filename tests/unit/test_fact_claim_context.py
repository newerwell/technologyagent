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


def test_latest_delivery_deadline_is_distinct_from_approved_quote_lead():
    answer = "P001/W01用户要求的最晚交期为7天；P001/S01报价交期为5天。"
    claims, violations = extract_business_claims(answer)
    assert not violations
    by_number = {claim.number: claim for claim in claims}
    assert by_number["7"].fields == frozenset({"max_lead_days"})
    assert by_number["5"].fields == frozenset({"lead_days"})
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


def test_parenthetical_available_does_not_rebind_preceding_shortage():
    answer = "W01 的 P003（火花塞）缺口 36 个（可用 4 个）。"
    evidence = [
        _fact("shortage", 36, "个", entity_id="I005", part_id="P003", warehouse_id="W01"),
        _fact("available", 4, "个", entity_id="I005", part_id="P003", warehouse_id="W01"),
    ]

    checked = validate_business_claims(answer, evidence)

    assert checked.passed
    assert not checked.violations


def test_inventory_record_count_is_not_on_hand_stock():
    answer = "W01 范围覆盖共 5 条库存记录。"
    evidence = [
        _fact("inventory_count", 5, "count", entity="query_aggregate", entity_id="W01-page",
              warehouse_id="W01"),
    ]

    claim = _claim(answer, 5)
    assert claim.fields == frozenset({"inventory_count"})
    assert validate_business_claims(answer, evidence).passed


def test_quote_quantity_uses_part_unit_and_allows_unscoped_warehouse():
    answer = "P001/W01/S01 报价 Q01 的最小起订量为 10 套。"
    evidence = [
        _fact("min_order_qty", 10, "count", entity="quote", entity_id="Q01",
              part_id="P001", supplier_id="S01"),
        _fact("part_unit", "套", "label", entity="quote", entity_id="Q01",
              part_id="P001", supplier_id="S01"),
    ]

    assert validate_business_claims(answer, evidence).passed


def test_quote_quantity_without_part_unit_is_not_accepted_as_business_unit():
    answer = "P001/W01/S01 报价 Q01 的最小起订量为 10 套。"
    evidence = [
        _fact("min_order_qty", 10, "count", entity="quote", entity_id="Q01",
              part_id="P001", supplier_id="S01"),
    ]

    checked = validate_business_claims(answer, evidence)

    assert not checked.passed


def test_quote_quantity_with_conflicting_part_unit_is_rejected():
    answer = "P001/W01/S01 报价 Q01 的最小起订量为 10 套。"
    evidence = [
        _fact("min_order_qty", 10, "count", entity="quote", entity_id="Q01",
              part_id="P001", supplier_id="S01"),
        _fact("part_unit", "个", "label", entity="quote", entity_id="Q01",
              part_id="P001", supplier_id="S01"),
    ]

    assert not validate_business_claims(answer, evidence).passed


def test_mixed_quote_table_cell_keeps_each_number_bound_to_its_local_field_and_supplier():
    answer = (
        "| 零件（仓库） | 有效报价与预览建议数量（quantity） |\n"
        "|---|---|\n"
        "| 刹车片 P001（W01） | 南方汽配（S02，交期12天，预览推荐）；"
        "华东制动（S01，交期5天）。预览建议数量为55套 |"
    )

    claims, violations = extract_business_claims(answer)
    assert not violations
    twelve = next(claim for claim in claims if claim.number == "12")
    five = next(claim for claim in claims if claim.number == "5")
    quantity = next(claim for claim in claims if claim.number == "55")
    assert twelve.fields == five.fields == frozenset({"lead_days"})
    assert twelve.scope == frozenset({"P001", "W01", "S02"})
    assert five.scope == frozenset({"P001", "W01", "S01"})
    assert quantity.fields == frozenset({"quantity"})


def test_unscoped_numeric_feedback_names_the_missing_entity_and_unit():
    checked = validate_business_claims("目标库存缺口为0。", [])

    assert not checked.passed
    assert any("claimed scope: none; unit: count" in issue and "exact entity" in issue
               for issue in checked.violations)

# --- N01：已出现的合法语言格式（A01/A02/A03） ---

def test_vertical_field_value_table_uses_field_cell():
    answer = "| 实体 | 字段 | 值 |\n|---|---|---|\n| P001/W01 | shortage | 55套 |"
    claim = _claim(answer, 55)

    assert claim.fields == frozenset({"shortage"})
    assert claim.scope == frozenset({"P001", "W01"})
    assert claim.unit == "套"
    assert validate_business_claims(answer, _facts()).passed


def test_table_keeps_supplier_and_quote_from_entity_columns():
    answer = "| 实体 | 报价 | 交期 |\n|---|---|---|\n| P001/W01/S01 | Q01 | 5天 |"
    evidence = _facts() + [
        _fact("lead_days", 12, "days", entity="quote", entity_id="Q02",
              part_id="P001", supplier_id="S02"),
    ]

    claim = _claim(answer, 5)

    assert claim.fields == frozenset({"lead_days"})
    assert claim.scope == frozenset({"P001", "W01", "S01", "Q01"})
    assert validate_business_claims(answer, evidence).passed


def test_separate_unit_clause_binds_only_same_quantity():
    answer = "P001，数量55，单位套。"
    claim = _claim(answer, 55)

    assert claim.fields == frozenset({"quantity"})
    assert claim.unit == "套"
    assert claim.scope == frozenset({"P001"})
    assert validate_business_claims(answer, _facts()).passed
    assert not validate_business_claims("P001，数量56，单位套。", _facts()).passed
    assert not validate_business_claims("P001，数量55，单位件。", _facts()).passed


def test_unit_column_is_not_lost_in_value_table():
    answer = "P001/W01：\n| 字段 | 值 | 单位 |\n|---|---|---|\n| quantity | 55 | 套 |"
    claim = _claim(answer, 55)

    assert claim.fields == frozenset({"quantity"})
    assert claim.unit == "套"
    assert claim.scope == frozenset({"P001", "W01"})
    assert validate_business_claims(answer, _facts()).passed


def test_bold_or_parenthesized_unit_keeps_same_meaning():
    for answer in ("P001/W01：缺口**55套**", "P001/W01：shortage=55（单位：套）"):
        claim = _claim(answer, 55)
        assert claim.fields == frozenset({"shortage"})
        assert claim.unit == "套"
        assert claim.scope == frozenset({"P001", "W01"})
        assert validate_business_claims(answer, _facts()).passed, answer


def test_header_scope_resets_at_new_entity_or_blank_block():
    answer = "P001/W01：\n\n| 实体 | 字段 | 值 |\n|---|---|---|\n| P004/W01 | shortage | 10条 |"
    claim = _claim(answer, 10)

    assert claim.scope == frozenset({"P004", "W01"})
    assert "P001" not in claim.scope
    assert validate_business_claims(answer, _facts()).passed

    ambiguous = "| 实体 | 字段 | 值 |\n|---|---|---|\n| P004/W01、P005/W02 | shortage | 10条 |"
    both = _facts() + [_fact("shortage", 10, "条", entity_id="I009", part_id="P005", warehouse_id="W02")]
    assert not validate_business_claims(ambiguous, both).passed


def test_delivery_limit_and_quote_lead_keep_distinct_fields():
    answer = "| 实体 | 报价交期 | 交期上限 |\n|---|---|---|\n| P001/W01/S01 | 5天 | 7天 |"
    claims, violations = extract_business_claims(answer)
    assert not violations
    by_number = {claim.number: claim for claim in claims}

    assert by_number["5"].fields == frozenset({"lead_days"})
    assert by_number["7"].fields == frozenset({"max_lead_days"})
    assert validate_business_claims(answer, _facts()).passed
