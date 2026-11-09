from decimal import Decimal

import pytest

from backend.app.agent.fact_checks import BusinessFact, FactIndex, FactKey
from backend.app.contracts.workflow import SourceRef


def test_snapshot_serializes_exact_facts_without_raw_payloads():
    from backend.app.agent.review_snapshot import make_review_input_snapshot

    fact_index = FactIndex(facts=(
        BusinessFact(
            key=FactKey("inventory", "I001", "shortage", part_id="P001", warehouse_id="W01"),
            value=Decimal("55.00"), unit="套", call_id="call-1",
            raw={"api_key": "never-copy-this", "untrusted": True},
        ),
        BusinessFact(
            key=FactKey("inventory", "I002", "warning", part_id="P003", warehouse_id="W01"),
            value=True, unit="boolean", call_id="call-2",
        ),
    ))

    snapshot = make_review_input_snapshot(
        candidate_answer="P001缺口55套。",
        original_request="查W01缺口",
        request_constraints={"warehouse_ids": ["W01"]},
        fact_index=fact_index,
        source_refs=[SourceRef(call_id="call-1", entity="inventory", id="I001")],
    )

    assert snapshot.facts[0].value == "55.00"
    assert snapshot.facts[1].value is True
    assert len(snapshot.facts[0].key) == 8
    assert snapshot.source_refs[0].id == "I001"
    assert "raw" not in snapshot.model_dump(mode="json")
    assert "never-copy-this" not in str(snapshot.model_dump(mode="json"))


def test_snapshot_rejects_non_finite_numeric_fact():
    from backend.app.agent.review_snapshot import make_review_input_snapshot

    facts = FactIndex(facts=(BusinessFact(
        key=FactKey("inventory", "I001", "shortage", part_id="P001"),
        value=float("inf"), unit="套", call_id="call-1",
    ),))

    with pytest.raises(ValueError, match="finite"):
        make_review_input_snapshot(
            candidate_answer="", original_request="q", request_constraints={},
            fact_index=facts, source_refs=[],
        )


def test_snapshot_preserves_quote_id_as_optional_entity_scope():
    from backend.app.agent.review_snapshot import make_review_input_snapshot

    facts = FactIndex(facts=(BusinessFact(
        key=FactKey("replenishment", "P001", "total_cents", part_id="P001", warehouse_id="W01",
                    supplier_id="S01", quote_id="Q01"),
        value=66000, unit="cents", call_id="preview",
    ),))

    snapshot = make_review_input_snapshot(
        candidate_answer="Q01 P001/W01/S01补货总额660.00元。", original_request="推荐供应商",
        request_constraints={}, fact_index=facts, source_refs=[],
    )

    assert snapshot.input_version == 1
    assert snapshot.facts[0].key["quote_id"] == "Q01"
