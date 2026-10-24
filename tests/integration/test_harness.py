"""P05 run级阶段、计划、评审和有界修订验收。"""

import pytest

from backend.app.agent.budget import RunBudget
from backend.app.agent.scripted_model import ScriptedModel, call_tool, token
from tests.integration.test_agent_tools import _run


@pytest.mark.asyncio
async def test_harness_emits_ordered_phases_and_evidence_backed_plan(db_name, mongo_admin):
    try:
        model = ScriptedModel(steps=[
            [call_tool("replenishment_preview", {"part_ids": ["P001"], "warehouse_id": "W01"})],
            [token("P001 在 W01 的缺口是55件，金额60500分。")],
        ])
        outcome, sink, _ = await _run(db_name, model)
        phases = [payload["phase"] for kind, payload in sink.events if kind == "phase"]
        plans = [payload for kind, payload in sink.events if kind == "plan"]
        reviews = [payload for kind, payload in sink.events if kind == "review"]
        assert outcome.status == "completed", (outcome, reviews, [kind for kind, _ in sink.events])
        assert phases == ["planning", "executing", "reviewing", "result"]
        assert plans[-1]["items"][0]["status"] == "done"
        assert plans[-1]["items"][0]["evidence_refs"]
        assert reviews[-1]["passed"] is True
    finally:
        mongo_admin.drop_database(db_name)


@pytest.mark.asyncio
async def test_harness_revises_wrong_numeric_answer_before_publishing(db_name, mongo_admin):
    try:
        model = ScriptedModel(steps=[
            [call_tool("replenishment_preview", {"part_ids": ["P001"], "warehouse_id": "W01"})],
            [token("P001 在 W01 的缺口是999件，金额60500分。")],
            [token("P001 在 W01 的缺口是55件，金额60500分。")],
        ])
        outcome, sink, _ = await _run(db_name, model)
        tokens = [payload["delta"] for kind, payload in sink.events if kind == "token"]
        reviews = [payload for kind, payload in sink.events if kind == "review"]
        assert outcome.status == "completed", (outcome, reviews)
        assert len(reviews) == 2 and reviews[0]["passed"] is False and reviews[1]["passed"] is True
        assert "999" not in "".join(tokens)
        assert "55件" in "".join(tokens)
    finally:
        mongo_admin.drop_database(db_name)


@pytest.mark.asyncio
async def test_harness_stops_after_three_hard_failures_without_publishing_answer(db_name, mongo_admin):
    try:
        model = ScriptedModel(steps=[
            [call_tool("replenishment_preview", {"part_ids": ["P001"], "warehouse_id": "W01"})],
            [token("P001 在 W01 的缺口是999件。")],
            [token("P001 在 W01 的缺口是998件。")],
            [token("P001 在 W01 的缺口是997件。")],
        ])
        outcome, sink, _ = await _run(db_name, model)
        reviews = [payload for kind, payload in sink.events if kind == "review"]
        assert outcome.status == "failed"
        assert len(reviews) == 3
        assert reviews[-1]["passed"] is False and reviews[-1]["revision_count"] == 2
        assert not [payload for kind, payload in sink.events if kind == "token"]
    finally:
        mongo_admin.drop_database(db_name)


@pytest.mark.asyncio
async def test_harness_stops_at_shared_model_budget(db_name, mongo_admin):
    try:
        model = ScriptedModel(steps=[[
            call_tool("inventory_get", {"inventory_id": "I001"})
        ]])
        outcome, sink, _ = await _run(db_name, model, budget=RunBudget("run_test", max_model_calls=1))
        assert outcome.status == "failed" and outcome.error_code == "LIMIT_EXCEEDED"
        assert not [payload for kind, payload in sink.events if kind == "token"]
    finally:
        mongo_admin.drop_database(db_name)
