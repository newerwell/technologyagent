"""N02：同一报价事实跨来源与单位表示归一，真冲突仍拒绝。

对应批次 20261109T132629Z-01573fa3ae 内层P03的MOQ歧义（A04）。
"""

from backend.app.agent.evidence import validate_business_claims
from backend.app.agent.fact_checks import extract_business_claims

EARLIER = "2026-11-09T10:00:00+00:00"
LATER = "2026-11-09T11:00:00+00:00"


def _fact(field, value, unit, *, entity_id, part_id="P001", supplier_id="S01", as_of=EARLIER,
          entity="quote"):
    return {
        "call_id": f"{entity_id}-{field}-{unit}-{as_of}",
        "entity": entity,
        "id": entity_id,
        "field": field,
        "value": value,
        "unit": unit,
        "part_id": part_id,
        "supplier_id": supplier_id,
        "as_of": as_of,
        "source_refs": [{"call_id": f"{entity_id}-{field}-{unit}-{as_of}", "entity": entity, "id": entity_id}],
    }


def _moq(value, unit, *, quote="Q01", part="P001", supplier="S01", as_of=EARLIER):
    return _fact("min_order_qty", value, unit, entity_id=quote, part_id=part,
                 supplier_id=supplier, as_of=as_of)


def _part_unit(label, *, quote="Q01", part="P001", supplier="S01"):
    return _fact("part_unit", label, "label", entity_id=quote, part_id=part, supplier_id=supplier)


def test_same_quote_moq_count_and_verified_part_unit_are_one_fact():
    facts = [
        _moq(10, "count", as_of=EARLIER),
        _part_unit("套"),
        _moq(10, "套", as_of=LATER),
    ]

    checked = validate_business_claims("P001/S01报价Q01的起订量为10套。", facts)

    assert checked.passed, checked.violations
    claims, violations = extract_business_claims("P001/S01报价Q01的起订量为10套。")
    assert not violations
    assert claims[0].fields == frozenset({"min_order_qty"})


def test_quote_moq_without_part_unit_does_not_gain_business_unit():
    facts = [_moq(10, "count")]

    assert not validate_business_claims("P001/S01报价Q01的起订量为10套。", facts).passed


def test_conflicting_part_unit_blocks_the_business_unit_claim():
    facts = [
        _moq(10, "count"),
        _part_unit("个"),
        _moq(10, "套", as_of=LATER),
    ]

    assert not validate_business_claims("P001/S01报价Q01的起订量为10套。", facts).passed


def test_same_value_from_another_quote_part_or_supplier_is_not_reused():
    q02 = [_moq(10, "套", quote="Q02", as_of=LATER), _part_unit("套", quote="Q02")]
    s02 = [_moq(10, "套", supplier="S02", as_of=LATER), _part_unit("套", supplier="S02")]
    p002 = [_moq(10, "套", part="P002", as_of=LATER), _part_unit("套", part="P002")]
    unverified_q01 = [_moq(10, "count")]

    answer = "P001/S01报价Q01的起订量为10套。"

    for facts in (q02, s02, p002):
        assert not validate_business_claims(answer, [*unverified_q01, *facts]).passed
    assert not validate_business_claims(answer, unverified_q01).passed


def test_latest_snapshot_decides_and_same_time_conflict_fails():
    outdated = [_moq(10, "count", as_of=EARLIER), _part_unit("套"), _moq(20, "套", as_of=LATER)]
    assert not validate_business_claims("P001/S01报价Q01的起订量为10套。", outdated).passed
    assert validate_business_claims("P001/S01报价Q01的起订量为20套。", outdated).passed

    conflict = [_moq(10, "count", as_of=EARLIER), _part_unit("套"), _moq(20, "套", as_of=EARLIER)]
    checked = validate_business_claims("P001/S01报价Q01的起订量为10套。", conflict)
    assert not checked.passed
    assert any("AMBIGUOUS" in issue for issue in checked.violations)
