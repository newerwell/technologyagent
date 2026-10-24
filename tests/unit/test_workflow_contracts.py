from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.app.contracts.events import PhasePayload, PlanPayload, RunView
from backend.app.contracts.workflow import PlanItem, ReviewResult, SourceRef


def test_v1_phase_and_plan_events_accept_additive_harness_state():
    phase = PhasePayload.model_validate({
        "phase": "reviewing", "iteration": 1, "task_type": "inventory", "revision_count": 1,
    })
    plan = PlanPayload.model_validate({
        "task_type": "inventory",
        "items": [{"id": "read", "title": "读取库存", "status": "done", "required_action": "inventory_page",
                   "evidence_refs": [{"call_id": "c1", "entity": "inventory", "id": "I001"}]}],
        "evidence_refs": [{"call_id": "c1", "entity": "inventory", "id": "I001"}],
    })

    assert phase.task_type == "inventory"
    assert phase.revision_count == 1
    assert plan.items[0].evidence_refs[0].id == "I001"


def test_run_view_persists_harness_snapshot_and_accepts_legacy_defaults():
    now = datetime.now(timezone.utc)
    legacy = RunView(
        id="run-1", thread_id="thread-1", status="running", last_seq=0,
        created_at=now, updated_at=now,
    )
    current = RunView(
        id="run-2", thread_id="thread-1", status="waiting_input", phase="executing",
        task_type="order", plan=[PlanItem(id="approval", title="等待审批")],
        evidence_refs=[SourceRef(call_id="c1", entity="order", id="P001")],
        review=ReviewResult(passed=False, revision_count=0), revision_count=0,
        last_seq=3, created_at=now, updated_at=now,
    )

    assert legacy.phase is None
    assert legacy.plan == []
    assert current.status == "waiting_input"
    assert current.phase == "executing"
    assert current.plan[0].status == "pending"
    assert current.review is not None and not current.review.passed


def test_review_payload_revision_count_cannot_exceed_two():
    with pytest.raises(ValidationError):
        ReviewResult(passed=False, revision_count=3)
