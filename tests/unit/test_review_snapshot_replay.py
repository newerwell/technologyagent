"""N00：把持久化review_input快照回放成同一FactIndex，锁定真实失败可离线复现。

快照只保留白名单事实字段，回放适配器必须只从这些字段重建事实与来源身份：
不复制模型正文、配置或raw密钥，也不得为缺失来源编造call_id。

合成夹具对应批次 20261109T132629Z-01573fa3ae（F02-F03 内层P03 2/9）及
A01–A07 反例；真实轨迹仍只保存在私有 .runtime，不进入 Git。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import pytest

from backend.app.agent.evidence import collect_evidence
from backend.app.agent.fact_checks import (
    BusinessFact,
    FactIndex,
    FactKey,
    extract_business_claims,
    validate_answer,
)
from backend.app.agent.review_snapshot import make_review_input_snapshot
from backend.app.contracts.events import ReviewFactSnapshot, ReviewInputSnapshot
from backend.app.ports.tools import ToolResult

_FACT_KEY_FIELDS = (
    "entity_type", "entity_id", "field", "part_id", "warehouse_id",
    "supplier_id", "order_id", "metric", "quote_id",
)
_REQUIRED_KEY_FIELDS = frozenset({"entity_type", "field"})
_NUMERIC_UNITS = frozenset({"count", "cents", "days", "yuan"})
_TEXT_UNITS = frozenset({"label", "identifier", "boolean"})


def _replayed_value(record: ReviewFactSnapshot) -> bool | int | float | str:
    """Restore the numeric/boolean/label/date semantics recorded in the snapshot."""
    if isinstance(record.value, bool):
        return record.value
    if record.unit in _TEXT_UNITS:
        return record.value
    try:
        number = Decimal(record.value)
    except (InvalidOperation, ValueError) as exc:
        if record.unit in _NUMERIC_UNITS:
            raise ValueError("review snapshot numeric value must be finite") from exc
        return record.value
    if not number.is_finite():
        if record.unit in _NUMERIC_UNITS:
            raise ValueError("review snapshot numeric value must be finite")
        return record.value
    return int(number) if number == number.to_integral_value() else float(number)


def fact_index_from_snapshot(snapshot: ReviewInputSnapshot) -> FactIndex:
    """Rebuild the review FactIndex from whitelisted snapshot fields only."""
    facts: list[BusinessFact] = []
    for record in snapshot.facts:
        key_fields = dict(record.key)
        if set(key_fields) - set(_FACT_KEY_FIELDS):
            raise ValueError("review snapshot fact key has unknown fields")
        if not _REQUIRED_KEY_FIELDS.issubset(key_fields):
            raise ValueError("review snapshot fact key is incomplete")
        if not record.call_id:
            raise ValueError("review snapshot fact has no traceable source")
        if not record.unit:
            raise ValueError("review snapshot fact has no unit")
        value = _replayed_value(record)
        raw: dict[str, Any] = {
            "call_id": record.call_id,
            "entity_type": key_fields["entity_type"],
            "entity": key_fields["entity_type"],
            "id": key_fields.get("entity_id") or "",
            "field": key_fields["field"],
            "value": value,
            "unit": record.unit,
            "as_of": record.as_of,
        }
        for name in ("part_id", "warehouse_id", "supplier_id", "order_id", "quote_id", "metric"):
            if key_fields.get(name):
                raw[name] = key_fields[name]
        facts.append(BusinessFact(
            key=FactKey(**{name: key_fields.get(name) for name in _FACT_KEY_FIELDS}),
            value=value,
            unit=record.unit,
            call_id=record.call_id,
            as_of=record.as_of,
            raw=raw,
        ))
    return FactIndex(tuple(facts))


def _tool_result(data: dict[str, Any], *, as_of: str) -> ToolResult:
    return ToolResult(ok=True, data=data, meta={"as_of": as_of, "data_source": "local_seed"})


def _synthetic_evidence() -> list[dict[str, Any]]:
    """Minimal synthetic copy of the 2026-11-09 batch shapes (W01/P001/S01/Q01)."""
    as_of = "2026-11-09T05:26:29+00:00"
    evidence = collect_evidence(
        "inventory_page",
        _tool_result({
            "records": [{
                "id": "I001", "part_id": "P001", "warehouse_id": "W01", "unit": "套",
                "on_hand": 15, "projected": 25, "shortage": 55, "reserved": 0,
                "inbound": 65, "safety_stock": 30, "target_stock": 80, "warning": True,
            }],
            "total": 1, "page": 1, "pages": 1, "page_size": 50,
        }, as_of=as_of),
        call_id="call-inventory",
        arguments={"warehouse_id": "W01", "page": 1, "page_size": 50},
    )
    evidence += collect_evidence(
        "quote_list",
        _tool_result({
            "records": [{
                "id": "Q01", "quote_id": "Q01", "part_id": "P001", "supplier_id": "S01",
                "unit": "套", "is_valid": True, "lead_days": 5, "min_order_qty": 10,
                "unit_price_cents": 1200, "valid_until": "2026-12-31",
            }],
            "total": 1, "page": 1, "pages": 1, "page_size": 50,
        }, as_of=as_of),
        call_id="call-quotes",
        arguments={"part_id": "P001"},
    )
    return evidence


_CANDIDATES = (
    "P001/W01缺口55套。",
    "P001/S01报价Q01交期5天。",
    "P001/S01报价Q01 is_valid=True。",
    "P001/W01库存15套。",
)


def _citation_signature(cited: tuple[dict[str, Any], ...]) -> list[tuple[str, ...]]:
    return sorted(
        (
            str(fact.get("field")),
            str(fact.get("value")),
            str(fact.get("unit")),
            str(fact.get("entity_type") or fact.get("entity") or ""),
            str(fact.get("part_id") or ""),
            str(fact.get("warehouse_id") or ""),
            str(fact.get("supplier_id") or ""),
            str(fact.get("quote_id") or ""),
        )
        for fact in cited
    )


def test_snapshot_roundtrip_keeps_numeric_boolean_and_quote_scope():
    from backend.app.agent.fact_checks import build_fact_index

    evidence = _synthetic_evidence()
    in_memory = build_fact_index(evidence)
    snapshot = make_review_input_snapshot(
        candidate_answer=_CANDIDATES[0], original_request="查W01缺口",
        request_constraints={"warehouse_ids": ["W01"]},
        fact_index=in_memory, source_refs=[],
    )
    replayed = fact_index_from_snapshot(snapshot)

    assert len(replayed.facts) == len(in_memory.facts)
    assert any(fact.value is True for fact in replayed.facts)
    assert any(fact.unit == "boolean" for fact in replayed.facts)
    assert any(fact.value == 55 for fact in replayed.facts)
    assert any(fact.key.quote_id == "Q01" and fact.key.part_id == "P001" for fact in replayed.facts)

    for answer in _CANDIDATES:
        original = validate_answer(answer, in_memory)
        replay = validate_answer(answer, replayed)
        assert (original.passed, original.violations) == (replay.passed, replay.violations), answer
        assert _citation_signature(original.cited_facts) == _citation_signature(replay.cited_facts), answer
        assert len(extract_business_claims(answer)[0]) == len(extract_business_claims(answer)[0])


def test_replayed_snapshot_preserves_the_recorded_zero_shortage_boundary():
    from backend.app.agent.evidence import validate_business_claims
    from backend.app.agent.fact_checks import build_fact_index

    evidence = [
        fact for fact in _synthetic_evidence()
    ] + [
        {
            "call_id": "call-inventory", "entity": "inventory", "id": "I002",
            "field": "shortage", "value": 0, "unit": "套",
            "part_id": "P002", "warehouse_id": "W01", "as_of": "2026-11-09T05:26:29+00:00",
            "source_refs": [{"call_id": "call-inventory", "entity": "inventory", "id": "I002"}],
        },
    ]
    in_memory = build_fact_index(evidence)
    snapshot = make_review_input_snapshot(
        candidate_answer="P001/W01缺口55套。", original_request="q",
        request_constraints={}, fact_index=in_memory, source_refs=[],
    )
    replayed = fact_index_from_snapshot(snapshot)

    answer = "P001/W01缺口55套。P002/W01无需补货。"
    assert validate_business_claims(answer, evidence).passed
    assert validate_business_claims(answer, [fact.raw for fact in replayed.facts if fact.raw]).passed


def test_missing_source_is_not_fabricated():
    record = ReviewFactSnapshot.model_construct(
        key={"entity_type": "inventory", "entity_id": "I001", "field": "shortage",
             "part_id": "P001", "warehouse_id": "W01"},
        value="55", unit="套", call_id="", as_of=None,
    )
    snapshot = ReviewInputSnapshot.model_construct(
        input_version=1, candidate_answer="P001/W01缺口55套。", original_request="q",
        request_constraints={}, facts=[record], source_refs=[],
    )

    with pytest.raises(ValueError, match="traceable source"):
        fact_index_from_snapshot(snapshot)


def test_unknown_key_and_non_finite_value_are_rejected():
    unknown_key = ReviewFactSnapshot.model_construct(
        key={"entity_type": "inventory", "entity_id": "I001", "field": "shortage",
             "bogus_scope": "W01"},
        value="55", unit="套", call_id="call-1", as_of=None,
    )
    non_finite = ReviewFactSnapshot.model_construct(
        key={"entity_type": "inventory", "entity_id": "I001", "field": "shortage"},
        value="NaN", unit="count", call_id="call-1", as_of=None,
    )

    for record, message in ((unknown_key, "unknown fields"), (non_finite, "finite")):
        snapshot = ReviewInputSnapshot.model_construct(
            input_version=1, candidate_answer="", original_request="q",
            request_constraints={}, facts=[record], source_refs=[],
        )
        with pytest.raises(ValueError, match=message):
            fact_index_from_snapshot(snapshot)
