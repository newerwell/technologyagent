"""P09 trace summaries describe persisted execution facts, not tool configuration."""

import asyncio

from backend.app.contracts.common import RequestContext


def _run(client, awaitable):
    async def invoke():
        return await awaitable
    return client.portal.call(invoke)


def test_trace_summary_counts_actual_calls_redacts_arguments_and_is_owner_scoped(seeded_client):
    container = seeded_client.app.state.container
    own = RequestContext("local-owner", "trace-own")
    foreign = RequestContext("other-owner", "trace-foreign")

    async def create_trace():
        run = await container.runs.create(None, "trace me", "trace-own", own)
        trace_ctx = RequestContext("local-owner", "trace-own", run_id=run.id)
        await container.runs.append_event(run.id, "model_started", {
            "call_id": "model-p09-1", "actor": "main",
        }, trace_ctx)
        await container.runs.append_event(run.id, "model_finished", {
            "call_id": "model-p09-1", "status": "success", "duration_ms": 18.5,
            "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
        }, trace_ctx)
        await container.runs.append_event(run.id, "tool_started", {
            "call_id": "call-p09-1", "name": "inventory_page", "actor": "analyst",
            "parent_call_id": "model-p09-1",
            "args_summary": {"api_key": "TRACE_SECRET_SENTINEL", "warehouse_id": "W01"},
            "simulation": False,
        }, trace_ctx)
        await asyncio.sleep(0.02)
        await container.runs.append_event(run.id, "tool_finished", {
            "call_id": "call-p09-1", "status": "error", "result_summary": "",
            "source": "", "error": "DEPENDENCY_UNAVAILABLE: offline", "simulation": False,
        }, trace_ctx)
        await container.mongo.db["runs"].update_one(
            {"_id": run.id, "owner_id": "local-owner"},
            {"$set": {"model_calls_used": 1}},
        )
        other = await container.runs.create(None, "foreign trace", "trace-foreign", foreign)
        return run.id, other.id

    run_id, foreign_run_id = _run(seeded_client, create_trace())
    response = seeded_client.get(f"/api/runs/{run_id}/trace")
    assert response.status_code == 200, response.text
    trace = response.json()["data"]
    assert trace["model"]["calls"] == 1
    assert trace["model"]["duration_ms"] == 18.5
    assert trace["model"]["usage"] == {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}
    assert trace["tools"]["registered_count"] > 0
    assert trace["tools"]["calls"] == 1
    assert trace["tools"]["failed"] == 1
    assert trace["recovery"]["retry_business_write"] is False
    assert trace["tool_calls"][0]["call_id"] == "call-p09-1"
    assert trace["tool_calls"][0]["actor"] == "analyst"
    assert trace["tool_calls"][0]["parent_call_id"] == "model-p09-1"
    assert trace["tool_calls"][0]["error_code"] == "DEPENDENCY_UNAVAILABLE"
    assert "TRACE_SECRET_SENTINEL" not in response.text
    assert seeded_client.get(f"/api/runs/{foreign_run_id}/trace").status_code == 404


def test_trace_summary_uses_persisted_call_count_and_marks_partial_usage(seeded_client):
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", "trace-partial")

    async def create_trace():
        run = await container.runs.create(None, "partial model trace", "trace-partial", ctx)
        trace_ctx = RequestContext("local-owner", "trace-partial", run_id=run.id)
        await container.runs.append_event(run.id, "run_started", {
            "status": "running", "thread_id": run.thread_id, "run_id": run.id, "model_mode": "live",
        }, trace_ctx)
        for call_id in ("call-1", "call-2"):
            await container.runs.append_event(run.id, "model_started", {
                "call_id": call_id, "actor": "main",
            }, trace_ctx)
        await container.runs.append_event(run.id, "model_finished", {
            "call_id": "call-1", "status": "success", "duration_ms": 5,
            "usage": {"total_tokens": 10},
        }, trace_ctx)
        await container.runs.append_event(run.id, "model_finished", {
            "call_id": "call-2", "status": "success", "duration_ms": 6, "usage": None,
        }, trace_ctx)
        await container.mongo.db["runs"].update_one(
            {"_id": run.id, "owner_id": "local-owner"},
            {"$set": {"model_calls": 3}},
        )
        return run.id

    run_id = _run(seeded_client, create_trace())
    response = seeded_client.get(f"/api/runs/{run_id}/trace")
    assert response.status_code == 200
    model = response.json()["data"]["model"]
    assert model["mode"] == "live"
    assert model["calls"] == 3
    assert model["event_calls"] == 2
    assert model["usage_completeness"] == "partial"
    assert model["usage_known_subtotal"] == {"total_tokens": 10}
    assert model["usage"] is None
