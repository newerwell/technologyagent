from __future__ import annotations

import pytest

from backend.app.agent.harness import InvalidPhaseTransition, transition_phase


def test_phase_moves_through_planning_execution_review_and_result():
    state = {"messages": [], "pending_interrupt": None}

    planning = transition_phase(state, "planning")
    executing = transition_phase({**state, **planning}, "executing")
    reviewing = transition_phase({**state, **executing}, "reviewing")
    result = transition_phase({**state, **executing, **reviewing}, "result")

    assert [planning["phase"], executing["phase"], reviewing["phase"], result["phase"]] == [
        "planning", "executing", "reviewing", "result"
    ]
    assert all(update["phase_changed"] for update in (planning, executing, reviewing, result))


def test_review_retry_is_limited_to_two_and_waiting_input_does_not_complete():
    state = {"phase": "reviewing", "revision_count": 0, "run_status": "running"}
    first = transition_phase(state, "executing")
    second = transition_phase({**state, **first, "phase": "reviewing"}, "executing")

    assert first["revision_count"] == 1
    assert second["revision_count"] == 2
    with pytest.raises(InvalidPhaseTransition, match="revision limit"):
        transition_phase({**state, **second, "phase": "reviewing"}, "executing")

    waiting = transition_phase({"phase": "executing", "run_status": "waiting_input"}, "executing")
    assert waiting["phase"] == "executing"
    assert waiting["phase_changed"] is False


def test_duplicate_phase_has_no_event_and_legacy_state_gets_defaults():
    duplicate = transition_phase({"phase": "planning"}, "planning")
    legacy = transition_phase({"messages": []}, "planning")

    assert duplicate["phase_changed"] is False
    assert legacy["task_type"] == "general"
    assert legacy["revision_count"] == 0
    assert legacy["evidence_refs"] == []


def test_phase_cannot_skip_review_or_leave_result():
    with pytest.raises(InvalidPhaseTransition):
        transition_phase({"phase": "planning"}, "result")
    with pytest.raises(InvalidPhaseTransition):
        transition_phase({"phase": "result"}, "executing")
