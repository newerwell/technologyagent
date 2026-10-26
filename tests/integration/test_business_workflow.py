"""HTTP regression for the complete proposal -> decision -> execution path."""

import hashlib
import json

from pymongo import MongoClient
import pytest


def _run(client, awaitable):
    async def invoke():
        return await awaitable
    return client.portal.call(invoke)


def test_approved_generic_proposal_executes_saved_payload_once(seeded_client):
    code = "HTTP-P08-EXEC"
    prepared = seeded_client.post("/api/mutations/proposals", json={
        "action": "supplier_create", "payload": {"code": code, "name": "HTTP执行供应商"},
    })
    assert prepared.status_code == 200
    proposal = prepared.json()["data"]
    decision = seeded_client.post(f"/api/mutations/proposals/{proposal['approval_id']}/resolve", json={
        "decision": "approve", "expected_version": proposal["version"], "decision_key": "approve-http-p08",
    })
    assert decision.status_code == 200
    response = seeded_client.post(f"/api/mutations/proposals/{proposal['approval_id']}/execute", json={
        "idempotency_key": "execute-http-p08",
    })
    assert response.status_code == 200, response.text
    replay = seeded_client.post(f"/api/mutations/proposals/{proposal['approval_id']}/execute", json={
        "idempotency_key": "execute-http-p08",
    })
    assert replay.status_code == 200 and replay.json()["data"] == response.json()["data"]
    container = seeded_client.app.state.container
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        db = sync[container.settings.mongodb_database]
        assert db.suppliers.count_documents({"code": code}) == 1
        assert db.approvals.find_one({"_id": proposal["approval_id"]})["status"] == "consumed"
    finally:
        sync.close()


@pytest.mark.parametrize(("decision", "recover_after_claim"), [
    ("approve", False), ("reject", False), ("approve", True),
])
def test_chat_owned_mutation_proposal_resumes_original_run_and_replays_once(seeded_client, decision, recover_after_claim):
    from datetime import datetime, timezone
    from backend.app.contracts.common import RequestContext

    container = seeded_client.app.state.container
    code = "CHAT-P09-" + decision.upper()
    ctx = RequestContext("local-owner", "chat-proposal-p09-" + decision, run_id=None)
    run = _run(seeded_client, container.runs.create_or_get(None, f"创建供应商 {code}", ctx.request_id, ctx))[0]
    run_ctx = RequestContext("local-owner", ctx.request_id, run_id=run.id)
    proposal = _run(seeded_client, container.approvals.request_mutation(
        "supplier_create", {"code": code, "name": "聊天审批供应商"}, run_ctx,
    ))
    _run(seeded_client, container.mongo.db["runs"].update_one(
        {"_id": run.id, "owner_id": "local-owner"},
        {"$set": {"status": "running", "active_started_at": datetime.now(timezone.utc)}},
    ))
    interrupt = {"interrupt_id": "chat-proposal-interrupt", "kind": "mutation_proposal",
        "proposal_id": proposal["proposal_id"], "approval_id": proposal["approval_id"],
        "action": proposal["action"], "payload": proposal["payload"],
        "fact_snapshot": proposal["fact_snapshot"], "version": proposal["version"], "summary": "等待确认供应商创建"}
    waiting = _run(seeded_client, container.runs.wait_for_input(run.id, interrupt, run_ctx))
    assert waiting.status == "waiting_input"
    decision_key = "chat-proposal-" + decision + "-p09"
    if recover_after_claim:
        from backend.app.contracts.order_workflow import ResumeRequest
        resume_request = ResumeRequest(
            interrupt_id=interrupt["interrupt_id"], decision=decision, expected_version=1,
            payload={}, idempotency_key=decision_key,
        )
        request_hash = hashlib.sha256(json.dumps(
            resume_request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        resume_record = {"interrupt_id": interrupt["interrupt_id"], "decision": decision,
            "expected_version": 1, "payload": {}, "idempotency_key": decision_key,
            "request_hash": request_hash, "workflow_kind": "mutation_proposal",
            "proposal_interrupt": interrupt}
        _run(seeded_client, container.runs.resume_waiting(
            run.id, interrupt["interrupt_id"], 1, run_ctx, resume_record,
        ))
        assert _run(seeded_client, container.order_workflows.recover_pending()) == 1
    response = seeded_client.post(f"/api/runs/{run.id}/resume", json={
        "interrupt_id": interrupt["interrupt_id"], "decision": decision, "expected_version": 1,
        "idempotency_key": decision_key, "payload": {},
    })
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "completed"
    replay = seeded_client.post(f"/api/runs/{run.id}/resume", json={
        "interrupt_id": interrupt["interrupt_id"], "decision": decision, "expected_version": 1,
        "idempotency_key": decision_key, "payload": {},
    })
    assert replay.status_code == 200 and replay.json()["data"]["status"] == "completed"
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        db = sync[container.settings.mongodb_database]
        assert db.suppliers.count_documents({"code": code}) == (1 if decision == "approve" else 0)
        assert db.operations.count_documents({"owner_id": "local-owner", "idempotency_key": decision_key}) == (1 if decision == "approve" else 0)
        saved = db.runs.find_one({"_id": run.id})
        assert saved["status"] == "completed" and saved["pending_interrupt"] is None
        assert db.approvals.find_one({"_id": proposal["approval_id"]})["status"] == ("consumed" if decision == "approve" else "rejected")
    finally:
        sync.close()


def test_graph_mutation_prepare_creates_durable_chat_interrupt(seeded_client):
    from datetime import datetime, timezone
    from backend.app.agent.budget import RunBudget
    from backend.app.agent.graph import GraphExecutor
    from backend.app.agent.scripted_model import ScriptedModel, call_tool
    from backend.app.contracts.agent import ExecutorInput
    from backend.app.contracts.common import RequestContext
    from backend.app.ports.tools import ToolResult
    from backend.app.services.chat import RunEventSink
    from mcp_server.tools.specs import MUTATION_PREPARE_SPEC

    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", "graph-proposal-p09")
    run = _run(seeded_client, container.runs.create_or_get(None, "创建供应商 GRAPH-P09", "graph-proposal-p09", ctx))[0]
    run_ctx = RequestContext("local-owner", ctx.request_id, run_id=run.id)
    _run(seeded_client, container.runs.append_event(run.id, "run_started", {
        "status": run.status, "thread_id": run.thread_id, "run_id": run.id, "model_mode": "fake",
    }, run_ctx))

    class ProposalRegistry:
        def available(self, _ctx): return [MUTATION_PREPARE_SPEC]
        async def invoke(self, name, arguments, tool_ctx, _budget):
            if name != "mutation_prepare": return ToolResult(ok=False, error={"code": "UNKNOWN_TOOL"})
            proposal = await container.approvals.request_mutation(arguments["action"], arguments["payload"], tool_ctx)
            return ToolResult(ok=True, data=proposal)
        async def close(self): pass

    async def factory(_ctx): return ProposalRegistry()
    model = ScriptedModel([[
        call_tool("mutation_prepare", {"action": "supplier_create", "payload": {
            "code": "GRAPH-P09", "name": "图调用审批供应商",
        }}, "graph-mutation-prepare"),
    ]])
    executor = GraphExecutor(model, factory, model_mode="fake", runs=container.runs)
    outcome = _run(seeded_client, executor._execute_graph(
        ExecutorInput(run_id=run.id, thread_id=run.thread_id, message="创建供应商 GRAPH-P09",
                      ctx=run_ctx, graph_version="v1"), RunEventSink(container.runs, run.id, run_ctx),
        RunBudget(run.id),
    ))
    assert outcome.status == "waiting_input", outcome.model_dump(mode="json")
    assert outcome.pending_interrupt["kind"] == "mutation_proposal"
    saved = seeded_client.get(f"/api/runs/{run.id}").json()["data"]
    assert saved["status"] == "waiting_input"
    assert saved["pending_interrupt"]["approval_id"] == outcome.pending_interrupt["approval_id"]


def test_generic_proposal_is_owner_scoped_and_can_execute_from_another_run(seeded_client):
    """A proposal belongs to its owner, not the run that happened to prepare it."""
    from backend.app.contracts.common import AppError, RequestContext

    container = seeded_client.app.state.container
    owner = RequestContext("local-owner", "proposal-origin", run_id="proposal-run")
    resumed = RequestContext("local-owner", "proposal-page", run_id="different-run")
    other_owner = RequestContext("other-owner", "foreign-page", run_id="different-run")
    code = "HTTP-P08-CROSS-RUN"

    async def prepare_and_approve():
        proposal = await container.approvals.request_mutation(
            "supplier_create", {"code": code, "name": "跨运行提案"}, owner,
        )
        await container.approvals.resolve_mutation(
            proposal["approval_id"], "approve", "approve-cross-run", owner,
            expected_version=proposal["version"],
        )
        return proposal

    proposal = _run(seeded_client, prepare_and_approve())
    result = _run(seeded_client, container.business_mutations.execute(
        proposal["approval_id"], "execute-cross-run", resumed,
    ))
    replay = _run(seeded_client, container.business_mutations.execute(
        proposal["approval_id"], "execute-cross-run", resumed,
    ))
    assert replay == result

    with pytest.raises(AppError) as exc:
        _run(seeded_client, container.business_mutations.execute(
            proposal["approval_id"], "execute-cross-run", other_owner,
        ))
    assert exc.value.code == "NOT_FOUND"

    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        db = sync[container.settings.mongodb_database]
        assert db.suppliers.count_documents({"code": code}) == 1
        assert db.approvals.find_one({"_id": proposal["approval_id"]})["status"] == "consumed"
        assert db.operations.count_documents({"owner_id": "local-owner", "idempotency_key": "execute-cross-run"}) == 1
    finally:
        sync.close()


@pytest.mark.parametrize("action,payload", [
    ("supplier_create", {"code": "BAD-NAME", "name": 123}),
    ("supplier_create", {"code": "BAD-RATING", "name": "坏类型", "credit_rating": {"x": 1}}),
    ("part_create", {"code": "BAD-SPEC", "name": "物料", "unit": "个", "specification": ["array"]}),
])
def test_invalid_action_payload_is_rejected_before_proposal_persistence(seeded_client, action, payload):
    response = seeded_client.post("/api/mutations/proposals", json={"action": action, "payload": payload})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    container = seeded_client.app.state.container
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        db = sync[container.settings.mongodb_database]
        assert db.approvals.count_documents({"proposal_payload": {"$exists": True}}) == 0
        assert db.operations.count_documents({"status": "succeeded"}) == 0
    finally:
        sync.close()


def test_legacy_persisted_bad_proposal_is_revalidated_before_operation_claim(seeded_client):
    from datetime import datetime, timezone

    from backend.app.contracts.common import RequestContext
    container = seeded_client.app.state.container
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    approval_id = "legacy-bad-payload"
    try:
        db = sync[container.settings.mongodb_database]
        db.approvals.insert_one({"_id": approval_id, "owner_id": "local-owner", "action": "supplier_create",
            "proposal_payload": {"code": "LEGACY-BAD", "name": 123}, "payload_hash": "legacy",
            "decision": "approve", "status": "pending", "created_at": datetime.now(timezone.utc)})
        ctx = RequestContext("local-owner", "legacy-test", run_id="legacy-test")
        try:
            _run(seeded_client, container.business_mutations.execute(approval_id, "legacy-key", ctx))
            assert False, "persisted legacy payload must be schema checked before claim"
        except Exception as exc:
            assert getattr(exc, "code", None) == "VALIDATION_ERROR"
        assert db.operations.count_documents({"owner_id": "local-owner"}) == 0
        assert db.suppliers.count_documents({"code": "LEGACY-BAD"}) == 0
    finally:
        sync.close()
