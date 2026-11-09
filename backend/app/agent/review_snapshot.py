"""Create a replayable, whitelisted snapshot of the exact review input."""

from __future__ import annotations

from dataclasses import fields
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.app.agent.fact_checks import BusinessFact, FactIndex
from backend.app.contracts.events import ReviewFactSnapshot, ReviewInputSnapshot
from backend.app.contracts.workflow import SourceRef

_FACT_KEY_FIELDS = frozenset({
    "entity_type", "entity_id", "field", "part_id", "warehouse_id",
    "supplier_id", "order_id", "metric", "quote_id",
})
_FACT_KEY_REQUIRED = _FACT_KEY_FIELDS - {"quote_id"}


def _serialize_fact(fact: BusinessFact) -> ReviewFactSnapshot:
    key = {field.name: getattr(fact.key, field.name) for field in fields(fact.key)
           if field.name != "quote_id" or getattr(fact.key, field.name) is not None}
    if not _FACT_KEY_REQUIRED.issubset(key) or not set(key).issubset(_FACT_KEY_FIELDS):
        raise ValueError("fact key fields do not match the review snapshot contract")
    value: str | bool
    if isinstance(fact.value, bool):
        value = fact.value
    elif isinstance(fact.value, str):
        value = fact.value
    elif isinstance(fact.value, (int, float, Decimal)):
        try:
            numeric = Decimal(str(fact.value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("review fact numeric value must be finite") from exc
        if not numeric.is_finite():
            raise ValueError("review fact numeric value must be finite")
        value = str(numeric)
    else:
        raise ValueError("review fact value must be a string, boolean, or finite number")
    return ReviewFactSnapshot(
        key=key, value=value, unit=fact.unit, call_id=fact.call_id, as_of=fact.as_of,
    )


def make_review_input_snapshot(
    *, candidate_answer: str, original_request: str,
    request_constraints: dict[str, Any], fact_index: FactIndex,
    source_refs: list[SourceRef],
) -> ReviewInputSnapshot:
    """Serialize only review candidate, saved constraints, verified facts and sources."""
    return ReviewInputSnapshot(
        input_version=1,
        candidate_answer=candidate_answer,
        original_request=original_request,
        request_constraints=request_constraints,
        facts=[_serialize_fact(fact) for fact in fact_index.facts],
        source_refs=source_refs,
    )
