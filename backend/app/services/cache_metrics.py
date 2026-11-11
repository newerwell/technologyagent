"""Validated, per-run DeepSeek input-cache metrics from persisted model events."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


_CACHE_FIELDS = (
    "prompt_tokens",
    "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens",
)


def _bucket() -> dict[str, Any]:
    return {
        "known_hit_tokens": 0,
        "known_miss_tokens": 0,
        "counted_calls": 0,
        "missing_calls": 0,
        "invalid_calls": 0,
        "failed_calls_with_usage": 0,
        "_valid_success_calls": 0,
    }


def _call_key(event: Mapping[str, Any], payload: Mapping[str, Any]) -> tuple[str | None, str] | None:
    call_id = payload.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        return None
    run_id = event.get("run_id")
    return (run_id if isinstance(run_id, str) else None, call_id)


def _group_value(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "unknown"
    return value.strip()[:80]


def _classify_usage(usage: object) -> tuple[str, tuple[int, int, int] | None]:
    if not isinstance(usage, Mapping):
        return "missing", None
    if any(field not in usage or usage[field] is None for field in _CACHE_FIELDS):
        return "missing", None
    values = tuple(usage[field] for field in _CACHE_FIELDS)
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
        return "invalid", None
    prompt_tokens, hit_tokens, miss_tokens = values
    if prompt_tokens != hit_tokens + miss_tokens:
        return "invalid", None
    return "valid", (prompt_tokens, hit_tokens, miss_tokens)


def _record_success(bucket: dict[str, Any], usage: object) -> None:
    category, values = _classify_usage(usage)
    if category == "missing":
        bucket["missing_calls"] += 1
    elif category == "invalid":
        bucket["invalid_calls"] += 1
    else:
        assert values is not None
        prompt_tokens, hit_tokens, miss_tokens = values
        bucket["_valid_success_calls"] += 1
        if prompt_tokens > 0:
            bucket["known_hit_tokens"] += hit_tokens
            bucket["known_miss_tokens"] += miss_tokens
            bucket["counted_calls"] += 1


def _public_bucket(bucket: Mapping[str, Any], *, event_coverage_complete: bool) -> dict[str, Any]:
    hit = int(bucket["known_hit_tokens"])
    miss = int(bucket["known_miss_tokens"])
    denominator = hit + miss
    valid_calls = int(bucket["_valid_success_calls"])
    missing_calls = int(bucket["missing_calls"])
    invalid_calls = int(bucket["invalid_calls"])
    completeness = (
        "missing" if valid_calls == 0
        else "partial" if missing_calls or invalid_calls or not event_coverage_complete
        else "complete"
    )
    complete_successes = (
        event_coverage_complete and valid_calls > 0 and missing_calls == 0 and invalid_calls == 0
    )
    return {
        "known_hit_tokens": hit,
        "known_miss_tokens": miss,
        "known_hit_rate": hit / denominator if denominator else None,
        "hit_rate": hit / denominator if denominator and complete_successes else None,
        "counted_calls": int(bucket["counted_calls"]),
        "missing_calls": missing_calls,
        "invalid_calls": invalid_calls,
        "failed_calls_with_usage": int(bucket["failed_calls_with_usage"]),
        "completeness": completeness,
    }


def summarize_cache_events(
    events: Sequence[Mapping[str, Any]], expected_model_calls: int,
) -> dict[str, Any]:
    """Summarize successful cache usage without turning missing data into zero.

    ``expected_model_calls`` is the persisted attempt count for the run. Duplicate
    copies of the same event are ignored by ``(run_id, call_id)``; conflicting
    copies make event coverage incomplete. Failed calls with usage are reported
    separately and never contribute to the successful-call hit rate.
    """
    starts: dict[tuple[str | None, str], Mapping[str, Any]] = {}
    finishes: dict[tuple[str | None, str], Mapping[str, Any]] = {}
    conflicts: set[tuple[str | None, str]] = set()
    malformed_events = 0

    for event in events:
        if not isinstance(event, Mapping):
            continue
        event_type = event.get("type")
        if event_type not in {"model_started", "model_finished"}:
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            malformed_events += 1
            continue
        key = _call_key(event, payload)
        if key is None:
            malformed_events += 1
            continue
        target = starts if event_type == "model_started" else finishes
        prior = target.get(key)
        if prior is not None and dict(prior) != dict(payload):
            conflicts.add(key)
        else:
            target[key] = payload

    expected_valid = (
        isinstance(expected_model_calls, int)
        and not isinstance(expected_model_calls, bool)
        and expected_model_calls >= 0
    )
    expected = expected_model_calls if expected_valid else 0
    keys = set(starts) | set(finishes)
    matched = set(starts) & set(finishes)
    event_coverage_complete = (
        expected_valid
        and len(keys) == expected
        and len(starts) == expected
        and len(finishes) == expected
        and matched == keys
        and not malformed_events
        and not conflicts
    )

    overall = _bucket()
    groups: dict[str, dict[str, dict[str, Any]]] = {}

    def group_bucket(purpose: object, actor: object) -> dict[str, Any]:
        purpose_key = _group_value(purpose)
        actor_key = _group_value(actor)
        return groups.setdefault(purpose_key, {}).setdefault(actor_key, _bucket())

    for key in matched:
        started = starts[key]
        finished = finishes[key]
        purpose = started.get("purpose", finished.get("purpose"))
        actor = started.get("actor", finished.get("actor"))
        grouped = group_bucket(purpose, actor)
        status = finished.get("status")
        usage = finished.get("usage")
        if status == "success":
            _record_success(overall, usage)
            _record_success(grouped, usage)
        elif status == "error":
            if isinstance(usage, Mapping) and bool(usage):
                overall["failed_calls_with_usage"] += 1
                grouped["failed_calls_with_usage"] += 1
        else:
            overall["missing_calls"] += 1
            grouped["missing_calls"] += 1

    unpaired_keys = keys - matched
    for key in unpaired_keys:
        payload = starts.get(key) or finishes.get(key) or {}
        grouped = group_bucket(payload.get("purpose"), payload.get("actor"))
        overall["missing_calls"] += 1
        grouped["missing_calls"] += 1

    unobserved_calls = max(0, expected - len(keys))
    if unobserved_calls:
        overall["missing_calls"] += unobserved_calls
        group_bucket("unknown", "unknown")["missing_calls"] += unobserved_calls

    public = _public_bucket(overall, event_coverage_complete=event_coverage_complete)
    public["by_purpose"] = {
        purpose: {
            actor: _public_bucket(bucket, event_coverage_complete=event_coverage_complete)
            for actor, bucket in sorted(actors.items())
        }
        for purpose, actors in sorted(groups.items())
    }
    return public
