"""P02 事件契约：fixture 全类型、UTC、seq 与 payload 校验。"""

from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.contracts.events import (
    EventEnvelope,
    EventType,
    ModelFinishedPayload,
    ModelStartedPayload,
    ReviewPayload,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "events" / "v1.json"


def load_events() -> list[EventEnvelope]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    return [EventEnvelope.model_validate(item) for item in payload["events"]]


def test_fixture_covers_all_event_types_and_utc():
    events = load_events()
    assert {event.type for event in events} == set(EventType.__args__)
    assert all(event.at.utcoffset() == timezone.utc.utcoffset(None) for event in events)
    assert [event.seq for event in events] == list(range(1, 16))
    starts = [event for event in events if event.type == "tool_started"]
    finishes = [event for event in events if event.type == "tool_finished"]
    assert {event.payload["call_id"] for event in starts} == {
        event.payload["call_id"] for event in finishes
    }


def test_event_requires_positive_seq():
    raw = load_events()[0].model_dump()
    raw["seq"] = 0
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(raw)


def test_event_requires_run_id():
    raw = load_events()[0].model_dump()
    del raw["run_id"]
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(raw)


def test_unknown_status_is_rejected():
    raw = load_events()[10].model_dump()
    raw["payload"]["status"] = "unknown"
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(raw)


def test_unknown_event_type_is_rejected():
    raw = load_events()[0].model_dump()
    raw["type"] = "not-an-event"
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(raw)


def test_invalid_payload_is_rejected():
    raw = load_events()[1].model_dump()
    del raw["payload"]["message_id"]
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(raw)


def test_legacy_review_payload_without_snapshot_remains_valid():
    assert ReviewPayload.model_validate({"passed": False}).review_input is None


def test_review_payload_accepts_typed_candidate_snapshot():
    payload = ReviewPayload.model_validate({
        "passed": False,
        "revision_count": 0,
        "review_input": {
            "input_version": 1,
            "candidate_answer": "候选正文",
            "original_request": "原始请求",
            "request_constraints": {"part_ids": ["P001"]},
            "facts": [{
                "key": {
                    "entity_type": "inventory", "entity_id": "I001", "field": "shortage",
                    "part_id": "P001", "warehouse_id": "W01", "supplier_id": None,
                    "order_id": None, "metric": None,
                },
                "value": "55", "unit": "套", "call_id": "call-1", "as_of": None,
            }],
            "source_refs": [],
        },
    })
    assert payload.review_input.candidate_answer == "候选正文"


def test_review_snapshot_rejects_unknown_fact_key():
    with pytest.raises(ValidationError):
        ReviewPayload.model_validate({
            "passed": False,
            "review_input": {
                "input_version": 1,
                "candidate_answer": "",
                "original_request": "q",
                "request_constraints": {},
                "facts": [{"key": {"field": "shortage", "secret": "x"},
                           "value": "1", "unit": "套", "call_id": "c"}],
                "source_refs": [],
            },
        })


def test_review_snapshot_rejects_unknown_version_and_extra_fields():
    base = {
        "input_version": 1,
        "candidate_answer": "",
        "original_request": "q",
        "request_constraints": {},
        "facts": [],
        "source_refs": [],
    }
    bad_version = {**base, "input_version": 2}
    with pytest.raises(ValidationError):
        ReviewPayload.model_validate({"passed": False, "review_input": bad_version})
    with pytest.raises(ValidationError):
        ReviewPayload.model_validate({
            "passed": False, "review_input": {**base, "messages": ["not allowed"]},
        })


def test_model_event_contracts_accept_cache_metadata_and_validate_first_output():
    started = ModelStartedPayload.model_validate({
        "call_id": "model-1", "actor": "analyst", "purpose": "agent_step",
        "model_name": "deepseek-test", "prompt_template_id": "ta-v2-base-1",
        "toolset_id": "sha256:abc",
    })
    finished = ModelFinishedPayload.model_validate({
        "call_id": "model-1", "status": "success", "duration_ms": 12,
        "first_output_ms": 4.5,
        "usage": {"prompt_tokens": 100, "prompt_cache_hit_tokens": 80,
                  "prompt_cache_miss_tokens": 20},
    })

    assert started.model_name == "deepseek-test"
    assert started.prompt_template_id == "ta-v2-base-1"
    assert started.toolset_id == "sha256:abc"
    assert finished.first_output_ms == 4.5
    with pytest.raises(ValidationError):
        ModelFinishedPayload.model_validate({
            "call_id": "model-1", "status": "success", "duration_ms": 12,
            "first_output_ms": -1,
        })
