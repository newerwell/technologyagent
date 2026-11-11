from __future__ import annotations

import importlib
from typing import Any

import pytest


def _summarize():
    try:
        module = importlib.import_module("backend.app.services.cache_metrics")
    except ModuleNotFoundError:
        module = None
    function = getattr(module, "summarize_cache_events", None)
    assert callable(function), "summarize_cache_events is required"
    return function


def _call(
    call_id: str,
    *,
    usage: dict[str, Any] | None,
    status: str = "success",
    purpose: str = "agent_step",
    actor: str = "analyst",
) -> list[dict[str, Any]]:
    return [
        {
            "type": "model_started",
            "run_id": "run-1",
            "payload": {"call_id": call_id, "purpose": purpose, "actor": actor},
        },
        {
            "type": "model_finished",
            "run_id": "run-1",
            "payload": {"call_id": call_id, "status": status, "usage": usage},
        },
    ]


def _usage(prompt: Any, hit: Any, miss: Any) -> dict[str, Any]:
    return {
        "prompt_tokens": prompt,
        "prompt_cache_hit_tokens": hit,
        "prompt_cache_miss_tokens": miss,
    }


def test_cache_metrics_uses_only_valid_successful_calls_and_groups_by_purpose_and_actor():
    summarize = _summarize()
    events = (
        _call("call-1", usage=_usage(100, 80, 20))
        + _call("call-2", usage=_usage(100, 20, 80), actor="order")
    )

    summary = summarize(events, expected_model_calls=2)

    assert summary["known_hit_tokens"] == 100
    assert summary["known_miss_tokens"] == 100
    assert summary["known_hit_rate"] == 0.5
    assert summary["hit_rate"] == 0.5
    assert summary["counted_calls"] == 2
    assert summary["missing_calls"] == 0
    assert summary["invalid_calls"] == 0
    assert summary["completeness"] == "complete"
    assert summary["by_purpose"]["agent_step"]["analyst"]["counted_calls"] == 1
    assert summary["by_purpose"]["agent_step"]["order"]["known_hit_tokens"] == 20


def test_missing_usage_keeps_known_subtotal_but_hides_full_hit_rate():
    summarize = _summarize()
    events = _call("call-1", usage=_usage(100, 80, 20)) + _call("call-2", usage=None)

    summary = summarize(events, expected_model_calls=2)

    assert summary["known_hit_rate"] == 0.8
    assert summary["hit_rate"] is None
    assert summary["known_hit_tokens"] == 80
    assert summary["known_miss_tokens"] == 20
    assert summary["counted_calls"] == 1
    assert summary["missing_calls"] == 1
    assert summary["completeness"] == "partial"


@pytest.mark.parametrize(
    "usage",
    [
        _usage(100, True, 99),
        _usage(100, 120, -20),
        _usage(100.0, 80, 20),
        _usage(100, 80, 19),
    ],
)
def test_invalid_cache_counters_are_never_used_as_known_totals(usage: dict[str, Any]):
    summary = _summarize()(_call("call-1", usage=usage), expected_model_calls=1)

    assert summary["known_hit_tokens"] == 0
    assert summary["known_miss_tokens"] == 0
    assert summary["known_hit_rate"] is None
    assert summary["hit_rate"] is None
    assert summary["counted_calls"] == 0
    assert summary["invalid_calls"] == 1


def test_missing_prompt_tokens_are_reported_as_missing_not_invalid():
    summary = _summarize()(
        _call("call-1", usage={
            "prompt_cache_hit_tokens": 80,
            "prompt_cache_miss_tokens": 20,
        }),
        expected_model_calls=1,
    )

    assert summary["missing_calls"] == 1
    assert summary["invalid_calls"] == 0


def test_zero_prompt_tokens_are_valid_but_do_not_enter_rate_denominator():
    summary = _summarize()(
        _call("call-1", usage=_usage(0, 0, 0)), expected_model_calls=1
    )

    assert summary["counted_calls"] == 0
    assert summary["known_hit_rate"] is None
    assert summary["hit_rate"] is None
    assert summary["completeness"] == "complete"


def test_duplicate_events_for_one_call_id_do_not_double_count():
    call_events = _call("call-1", usage=_usage(100, 80, 20))
    summary = _summarize()(call_events + call_events, expected_model_calls=1)

    assert summary["counted_calls"] == 1
    assert summary["known_hit_tokens"] == 80
    assert summary["hit_rate"] == 0.8


@pytest.mark.parametrize(
    "events",
    [
        [{"type": "model_started", "run_id": "run-1", "payload": {"call_id": "call-1"}}],
        [{"type": "model_finished", "run_id": "run-1", "payload": {
            "call_id": "call-1", "status": "success", "usage": _usage(100, 80, 20),
        }}],
    ],
)
def test_unpaired_start_or_finish_marks_event_coverage_missing(events: list[dict[str, Any]]):
    summary = _summarize()(events, expected_model_calls=1)

    assert summary["hit_rate"] is None
    assert summary["missing_calls"] == 1
    assert summary["completeness"] == "missing"


def test_failed_call_usage_is_separate_from_success_cache_rate():
    summary = _summarize()(
        _call("call-1", usage=_usage(100, 80, 20), status="error"),
        expected_model_calls=1,
    )

    assert summary["counted_calls"] == 0
    assert summary["known_hit_tokens"] == 0
    assert summary["known_miss_tokens"] == 0
    assert summary["hit_rate"] is None
    assert summary["failed_calls_with_usage"] == 1
    assert summary["completeness"] == "missing"


def test_expected_model_call_count_gaps_hide_full_hit_rate():
    summary = _summarize()(
        _call("call-1", usage=_usage(100, 80, 20)), expected_model_calls=2
    )

    assert summary["known_hit_rate"] == 0.8
    assert summary["hit_rate"] is None
    assert summary["missing_calls"] == 1
    assert summary["completeness"] == "partial"
