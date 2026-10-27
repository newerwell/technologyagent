"""P02 事件契约：fixture 全类型、UTC、seq 与 payload 校验。"""

from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.contracts.events import EventEnvelope, EventType

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
