"""P04 interrupt checkpoint survives the request boundary and resumes the same run."""

import pytest
from pymongo import MongoClient


def test_supplement_and_approval_resume_same_run_with_persistent_checkpoint(seeded_client):
    started = seeded_client.post("/api/order-workflows", json={
        "message": "刹车片补到目标库存，7天内到货，生成订单",
        "request_id": "workflow-checkpoint-1",
        "draft": {"part_ids": ["P001"], "max_lead_days": 7},
    })
    assert started.status_code == 200, started.text
    run = started.json()["data"]
    assert run["status"] == "waiting_input"
    assert run["pending_interrupt"]["kind"] == "supplement"
    assert run["phase"] == "executing" and run["task_type"] == "order"
    assert run["plan"] and run["plan"][0]["status"] == "pending"
    assert run["pending_interrupt"]["fields"] == ["warehouse_id"]
    original_run_id = run["id"]
    container = seeded_client.app.state.container
    # Reopen the actual Mongo saver before resume to cover backend lifecycle recovery.
    def reopen_saver():
        container.mongo.checkpointer.close()
        container.mongo._checkpoint_client.close()
        container.mongo._checkpointer = None
        container.mongo._checkpoint_client = None
    seeded_client.portal.call(reopen_saver)
    seeded_client.portal.call(container.mongo.configure_checkpointer)
    recovered_count = seeded_client.portal.call(seeded_client.app.state.container.runs.recover_orphans)
    assert recovered_count == 0
    restored = seeded_client.get(f"/api/runs/{original_run_id}").json()["data"]
    assert restored["status"] == "waiting_input"
    assert restored["pending_interrupt"]["interrupt_id"] == run["pending_interrupt"]["interrupt_id"]
    before = seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"]
    assert before == 2

    approval_wait = seeded_client.post(f"/api/runs/{original_run_id}/resume", json={
        "interrupt_id": run["pending_interrupt"]["interrupt_id"],
        "decision": "supplement", "expected_version": None,
        "payload": {"warehouse_id": "W01"}, "idempotency_key": "supplement-1",
    })
    assert approval_wait.status_code == 200, approval_wait.text
    waiting = approval_wait.json()["data"]
    assert waiting["id"] == original_run_id
    assert waiting["status"] == "waiting_input"
    assert waiting["pending_interrupt"]["kind"] == "approval"
    assert waiting["pending_interrupt"]["version"] == 1
    assert waiting["plan"][0]["status"] == "done"
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before

    edited = seeded_client.post(f"/api/runs/{original_run_id}/resume", json={
        "interrupt_id": waiting["pending_interrupt"]["interrupt_id"],
        "decision": "edit", "expected_version": 1,
        "payload": {"items": [{"part_id": "P001", "quote_id": "Q01", "quantity": 60}]},
        "idempotency_key": "workflow-edit-1",
    })
    assert edited.status_code == 200, edited.text
    waiting_v2 = edited.json()["data"]
    assert waiting_v2["status"] == "waiting_input"
    assert waiting_v2["pending_interrupt"]["kind"] == "approval"
    assert waiting_v2["pending_interrupt"]["version"] == 2
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before

    approved = seeded_client.post(f"/api/runs/{original_run_id}/resume", json={
        "interrupt_id": waiting_v2["pending_interrupt"]["interrupt_id"],
        "decision": "approve", "expected_version": 2,
        "payload": {}, "idempotency_key": "workflow-create-2",
    })
    assert approved.status_code == 200, approved.text
    final = approved.json()["data"]
    assert final["id"] == original_run_id
    assert final["status"] == "completed"
    assert final["pending_interrupt"] is None
    assert final["phase"] == "result" and final["review"]["passed"] is True
    harness_events = seeded_client.get(f"/api/runs/{original_run_id}/events", params={"after_seq": 0}).json()["data"]
    assert [event["payload"]["phase"] for event in harness_events if event["type"] == "phase"] == [
        "planning", "executing", "reviewing", "result"
    ]
    assert any(event["type"] == "review" and event["payload"]["passed"] is True for event in harness_events)
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before + 1
    order = seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["records"][0]
    assert order["total_cents"] == 72000


def test_stale_interrupt_and_cross_owner_resume_are_rejected(seeded_client):
    started = seeded_client.post("/api/order-workflows", json={
        "message": "补货 P001", "request_id": "workflow-owner-1",
        "draft": {"part_ids": ["P001"], "max_lead_days": 7},
    })
    run = started.json()["data"]
    stale = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": "old-interrupt", "decision": "supplement", "expected_version": None,
        "payload": {"warehouse_id": "W01"}, "idempotency_key": "stale",
    })
    assert stale.status_code == 409

    from backend.app.api.dependencies import get_context
    from backend.app.contracts.common import RequestContext
    seeded_client.app.dependency_overrides[get_context] = lambda: RequestContext(owner_id="owner-b", request_id="owner-b")
    owner_b = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": run["pending_interrupt"]["interrupt_id"], "decision": "supplement",
        "expected_version": None, "payload": {"warehouse_id": "W01"}, "idempotency_key": "owner-b",
    })
    assert owner_b.status_code == 404
    seeded_client.app.dependency_overrides.pop(get_context, None)


def test_rejecting_persisted_approval_finishes_run_without_order(seeded_client):
    before = seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"]
    started = seeded_client.post("/api/order-workflows", json={
        "message": "刹车片补货，7天内到货", "request_id": "workflow-reject-1",
        "draft": {"part_ids": ["P001"], "max_lead_days": 7},
    })
    assert started.status_code == 200, started.text
    run = started.json()["data"]
    supplemented = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": run["pending_interrupt"]["interrupt_id"], "decision": "supplement",
        "expected_version": None, "payload": {"warehouse_id": "W01"},
        "idempotency_key": "workflow-reject-supplement",
    })
    assert supplemented.status_code == 200, supplemented.text
    waiting = supplemented.json()["data"]
    draft_id = waiting["pending_interrupt"]["draft_id"]
    rejected = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": waiting["pending_interrupt"]["interrupt_id"], "decision": "reject",
        "expected_version": 1, "payload": {}, "idempotency_key": "workflow-reject-decision",
    })
    assert rejected.status_code == 200, rejected.text
    final = rejected.json()["data"]
    conversation = seeded_client.get(f"/api/conversations/{run['thread_id']}").json()["data"]
    assistant = next(message for message in conversation["messages"] if message["role"] == "assistant")
    assert final["status"] == "completed"
    assert "拒绝" in assistant["content"]
    assert seeded_client.get(f"/api/drafts/{draft_id}").json()["data"]["state"] == "rejected"
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before


def test_waiting_order_run_can_be_cancelled_and_thread_released(seeded_client):
    started = seeded_client.post("/api/order-workflows", json={
        "message": "补货 P001", "request_id": "cancel-waiting-order",
        "draft": {"part_ids": ["P001"], "max_lead_days": 7},
    })
    run = started.json()["data"]
    assert run["status"] == "waiting_input"
    cancelled = seeded_client.post(f"/api/runs/{run['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "cancelled"
    assert cancelled.json()["data"]["pending_interrupt"] is None
    resume = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": run["pending_interrupt"]["interrupt_id"], "decision": "supplement",
        "expected_version": None, "payload": {"warehouse_id": "W01"}, "idempotency_key": "after-cancel",
    })
    assert resume.status_code == 409
    new = seeded_client.post("/api/order-workflows", json={
        "message": "another order", "request_id": "after-cancel-new", "thread_id": run["thread_id"],
        "draft": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
    })
    assert new.status_code == 200, new.text


def test_cancel_before_commit_prevents_order_side_effects(seeded_client):
    started = seeded_client.post("/api/order-workflows", json={
        "message": "补货 P001", "request_id": "cancel-before-commit",
        "draft": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
    })
    run = started.json()["data"]
    container = seeded_client.app.state.container
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    operations = sync[container.settings.mongodb_database]["operations"]
    def cancel_after_claim(point):
        if point == "after_claim":
            sync[container.settings.mongodb_database]["runs"].update_one(
                {"_id": run["id"]}, {"$set": {"cancel_requested": True}}
            )
    container.mutations._fault_hook = cancel_after_claim
    response = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": run["pending_interrupt"]["interrupt_id"], "decision": "approve",
        "expected_version": run["pending_interrupt"]["version"], "payload": {},
        "idempotency_key": "cancel-before-commit-key",
    })
    container.mutations._fault_hook = None
    try:
        assert response.status_code == 200, response.text
        assert response.json()["data"]["status"] == "cancelled"
        assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == 2
        inventory = seeded_client.get("/api/inventory?warehouse_id=W01&part_name=刹车片").json()["data"]["records"]
        p001 = next(record for record in inventory if record["part_id"] == "P001")
        assert (p001["on_hand"], p001["inbound"]) == (20, 10)
        operation = operations.find_one({"owner_id": "local-owner", "idempotency_key": "cancel-before-commit-key"})
        assert operation["status"] == "failed"
    finally:
        sync.close()


def test_cancel_after_commit_keeps_real_order_result(seeded_client):
    started = seeded_client.post("/api/order-workflows", json={
        "message": "补货 P001", "request_id": "cancel-after-commit",
        "draft": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
    })
    run = started.json()["data"]
    container = seeded_client.app.state.container
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    def request_cancel_after_commit(point):
        if point == "after_commit_before_response":
            sync[container.settings.mongodb_database]["runs"].update_one(
                {"_id": run["id"]}, {"$set": {"cancel_requested": True}}
            )
    container.mutations._fault_hook = request_cancel_after_commit
    response = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": run["pending_interrupt"]["interrupt_id"], "decision": "approve",
        "expected_version": run["pending_interrupt"]["version"], "payload": {},
        "idempotency_key": "cancel-after-commit-key",
    })
    container.mutations._fault_hook = None
    try:
        assert response.status_code == 200, response.text
        assert response.json()["data"]["status"] == "completed"
        assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == 3
        conversation = seeded_client.get(f"/api/conversations/{run['thread_id']}").json()["data"]
        assistant = next(message for message in conversation["messages"] if message["role"] == "assistant")
        assert "已创建" in assistant["content"]
        assert "PO-" in assistant["content"]
    finally:
        sync.close()


def test_invalid_edit_does_not_consume_order_interrupt(seeded_client):
    started = seeded_client.post("/api/order-workflows", json={
        "message": "补货 P001", "request_id": "bad-edit-retain-wait",
        "draft": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
    })
    run = started.json()["data"]
    interrupt = run["pending_interrupt"]
    response = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": interrupt["interrupt_id"], "decision": "edit", "expected_version": interrupt["version"],
        "payload": {}, "idempotency_key": "bad-edit-retain",
    })
    assert response.status_code == 422
    current = seeded_client.get(f"/api/runs/{run['id']}").json()["data"]
    assert current["status"] == "waiting_input"
    assert current["pending_interrupt"]["interrupt_id"] == interrupt["interrupt_id"]
    retried = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": interrupt["interrupt_id"], "decision": "reject", "expected_version": interrupt["version"],
        "payload": {}, "idempotency_key": "valid-retry-after-bad-edit",
    })
    assert retried.status_code == 200, retried.text


def test_invalid_supplement_warehouse_does_not_consume_interrupt(seeded_client):
    started = seeded_client.post("/api/order-workflows", json={
        "message": "补货 P001", "request_id": "bad-warehouse-retain-wait",
        "draft": {"part_ids": ["P001"], "max_lead_days": 7},
    })
    run = started.json()["data"]
    interrupt = run["pending_interrupt"]
    bad = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": interrupt["interrupt_id"], "decision": "supplement", "expected_version": None,
        "payload": {"warehouse_id": "W99"}, "idempotency_key": "bad-warehouse-retain",
    })
    assert bad.status_code == 422
    current = seeded_client.get(f"/api/runs/{run['id']}").json()["data"]
    assert current["status"] == "waiting_input"
    assert current["pending_interrupt"]["interrupt_id"] == interrupt["interrupt_id"]
    good = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": interrupt["interrupt_id"], "decision": "supplement", "expected_version": None,
        "payload": {"warehouse_id": "W01"}, "idempotency_key": "good-warehouse-after-bad",
    })
    assert good.status_code == 200, good.text


def test_replaying_successful_order_decision_returns_same_run_and_order(seeded_client):
    started = seeded_client.post("/api/order-workflows", json={
        "message": "补货 P001", "request_id": "approve-replay",
        "draft": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
    })
    run = started.json()["data"]
    decision = {
        "interrupt_id": run["pending_interrupt"]["interrupt_id"], "decision": "approve",
        "expected_version": run["pending_interrupt"]["version"], "payload": {}, "idempotency_key": "approve-replay-key",
    }
    first = seeded_client.post(f"/api/runs/{run['id']}/resume", json=decision)
    second = seeded_client.post(f"/api/runs/{run['id']}/resume", json=decision)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["data"]["id"] == second.json()["data"]["id"] == run["id"]
    assert first.json()["data"]["status"] == second.json()["data"]["status"] == "completed"
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == 3


def test_resume_claim_crash_recovers_from_persisted_checkpoint(seeded_client):
    started = seeded_client.post("/api/order-workflows", json={
        "message": "补货 P001", "request_id": "resume-crash-before-graph",
        "draft": {"part_ids": ["P001"], "max_lead_days": 7},
    })
    run = started.json()["data"]

    workflows = seeded_client.app.state.container.order_workflows
    from backend.app.contracts.common import RequestContext
    from backend.app.contracts.order_workflow import ResumeRequest
    request = ResumeRequest(
        interrupt_id=run["pending_interrupt"]["interrupt_id"], decision="supplement",
        expected_version=None, payload={"warehouse_id": "W01"}, idempotency_key="resume-crash-key",
    )

    import hashlib, json
    request_payload = request.model_dump(mode="json")
    stored = {**request_payload, "request_hash": hashlib.sha256(json.dumps(
        request_payload, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()}
    async def claim_then_crash():
        return await seeded_client.app.state.container.runs.resume_waiting(
            run["id"], request.interrupt_id, request.expected_version,
            RequestContext(owner_id="local-owner", request_id="resume-crash-key", run_id=run["id"]), stored,
        )
    claimed, did_claim = seeded_client.portal.call(claim_then_crash)
    assert did_claim is True
    assert claimed.status == "running"
    pending = seeded_client.get(f"/api/runs/{run['id']}").json()["data"]
    assert pending["status"] == "running"
    assert pending["pending_interrupt"] is None

    container = seeded_client.app.state.container
    def reopen_saver():
        container.mongo.checkpointer.close()
        container.mongo._checkpoint_client.close()
        container.mongo._checkpointer = None
        container.mongo._checkpoint_client = None
        return container.mongo.configure_checkpointer()
    seeded_client.portal.call(reopen_saver)
    recovered = seeded_client.portal.call(workflows.recover_pending)
    assert recovered == 1
    restored = seeded_client.get(f"/api/runs/{run['id']}").json()["data"]
    assert restored["status"] == "waiting_input"
    assert restored["pending_interrupt"]["kind"] == "approval"


def test_orders_page_draft_metadata_resumes_owning_run(seeded_client):
    started = seeded_client.post("/api/order-workflows", json={
        "message": "补货 P001", "request_id": "orders-page-shared-run",
        "draft": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
    })
    run = started.json()["data"]
    drafts = seeded_client.get("/api/drafts").json()["data"]
    owned = next(draft for draft in drafts if draft.get("workflow", {}).get("run_id") == run["id"])
    interrupt = owned["workflow"]["pending_interrupt"]
    assert interrupt["draft_id"] == owned["id"]
    resumed = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": interrupt["interrupt_id"], "decision": "approve",
        "expected_version": interrupt["version"], "payload": {},
        "idempotency_key": "orders-page-shared-decision",
    })
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["data"]["status"] == "completed"


def test_commit_before_run_settlement_recovers_same_order_after_restart(seeded_client):
    started = seeded_client.post("/api/order-workflows", json={
        "message": "补货 P001", "request_id": "commit-before-settle",
        "draft": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
    })
    run = started.json()["data"]
    request = {
        "interrupt_id": run["pending_interrupt"]["interrupt_id"], "decision": "approve",
        "expected_version": run["pending_interrupt"]["version"], "payload": {},
        "idempotency_key": "commit-before-settle-key",
    }
    import hashlib, json
    request_hash = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    stored = {**request, "request_hash": request_hash}
    from backend.app.contracts.common import RequestContext
    ctx = RequestContext(owner_id="local-owner", request_id=request["idempotency_key"], run_id=run["id"])
    container = seeded_client.app.state.container
    async def claim():
        return await container.runs.resume_waiting(
            run["id"], request["interrupt_id"], request["expected_version"], ctx, stored,
        )
    _, did_claim = seeded_client.portal.call(claim)
    assert did_claim

    from langgraph.types import Command
    from backend.app.agent.order_nodes import workflow_config
    graph_value = {"decision": "approve", "idempotency_key": request["idempotency_key"], "payload": {}}
    seeded_client.portal.call(lambda: container.order_workflows._graph().ainvoke(
        Command(resume=graph_value), config=workflow_config(run["thread_id"], run["id"]),
    ))
    before = seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"]
    assert before == 3
    assert seeded_client.get(f"/api/runs/{run['id']}").json()["data"]["status"] == "running"

    def reopen_saver():
        container.mongo.checkpointer.close()
        container.mongo._checkpoint_client.close()
        container.mongo._checkpointer = None
        container.mongo._checkpoint_client = None
        return container.mongo.configure_checkpointer()
    seeded_client.portal.call(reopen_saver)
    assert seeded_client.portal.call(container.order_workflows.recover_pending) == 1
    assert seeded_client.get(f"/api/runs/{run['id']}").json()["data"]["status"] == "completed"
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before


def test_multiple_supplier_drafts_are_confirmed_independently(seeded_client):
    from pymongo import MongoClient
    container = seeded_client.app.state.container
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        sync[container.settings.mongodb_database]["inventories"].update_one(
            {"_id": "I003"}, {"$set": {"on_hand": 0, "reserved": 0, "inbound": 0, "version": 2}}
        )
    finally:
        sync.close()
    started = seeded_client.post("/api/order-workflows", json={
        "message": "补货两种零件", "request_id": "multi-supplier-run",
        "draft": {"part_ids": ["P001", "P002"], "warehouse_id": "W01"},
    })
    run = started.json()["data"]
    assert run["status"] == "waiting_input", started.text
    run_doc = seeded_client.portal.call(lambda: container.mongo.db["runs"].find_one({"_id": run["id"]}))
    assert run_doc["active_started_at"] is None
    first_active_seconds = run_doc["active_seconds_used"]
    first_interrupt = run["pending_interrupt"]
    first_draft_id = first_interrupt["draft_id"]
    first = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": first_interrupt["interrupt_id"], "decision": "approve",
        "expected_version": first_interrupt["version"], "payload": {},
        "idempotency_key": "multi-first-approve",
    })
    assert first.status_code == 200, first.text
    second_run = first.json()["data"]
    assert second_run["status"] == "waiting_input"
    run_doc = seeded_client.portal.call(lambda: container.mongo.db["runs"].find_one({"_id": run["id"]}))
    assert run_doc["active_started_at"] is None
    assert run_doc["active_seconds_used"] >= first_active_seconds
    after_first_decision = run_doc["active_seconds_used"]
    second_interrupt = second_run["pending_interrupt"]
    assert second_interrupt["draft_id"] != first_draft_id
    second = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": second_interrupt["interrupt_id"], "decision": "approve",
        "expected_version": second_interrupt["version"], "payload": {},
        "idempotency_key": "multi-second-approve",
    })
    assert second.status_code == 200, second.text
    assert second.json()["data"]["status"] == "completed"
    run_doc = seeded_client.portal.call(lambda: container.mongo.db["runs"].find_one({"_id": run["id"]}))
    assert run_doc["active_started_at"] is None
    assert run_doc["active_seconds_used"] >= after_first_decision
    orders = seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]
    assert orders["total"] == 4


def test_cancel_second_supplier_draft_preserves_first_committed_order(seeded_client):
    from pymongo import MongoClient
    container = seeded_client.app.state.container
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        sync[container.settings.mongodb_database]["inventories"].update_one(
            {"_id": "I003"}, {"$set": {"on_hand": 0, "reserved": 0, "inbound": 0, "version": 2}}
        )
    finally:
        sync.close()
    before = seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"]
    started = seeded_client.post("/api/order-workflows", json={
        "message": "补货两种零件", "request_id": "multi-cancel-after-first-commit",
        "draft": {"part_ids": ["P001", "P002"], "warehouse_id": "W01"},
    })
    run = started.json()["data"]
    assert run["status"] == "waiting_input", started.text
    first_interrupt = run["pending_interrupt"]
    first = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": first_interrupt["interrupt_id"], "decision": "approve",
        "expected_version": first_interrupt["version"], "payload": {},
        "idempotency_key": "multi-cancel-first-approve",
    })
    assert first.status_code == 200, first.text
    waiting_second = first.json()["data"]
    assert waiting_second["status"] == "waiting_input"
    cancelled = seeded_client.post(f"/api/runs/{run['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    view = cancelled.json()["data"]
    assert view["status"] == "cancelled"
    assert view["committed_facts"] is True
    assert "已提交订单号" in view["summary"]
    assert "未创建订单" not in view["summary"]
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before + 1


def test_live_order_intent_is_idempotent_and_counted_in_persisted_run_budget(seeded_client):
    from backend.app.contracts.agent import ModelDelta, ModelToolCall
    from backend.app.contracts.order_workflow import WorkflowStartRequest

    class CountingIntentModel:
        def __init__(self):
            self.calls = 0
        async def stream(self, _messages, _tools, _ctx):
            self.calls += 1
            yield ModelDelta(kind="tool_call", tool_call=ModelToolCall(
                id="intent", name="order_draft_prepare",
                arguments='{"part_name":"刹车片","max_lead_days":7}', index=0,
            ))

    model = CountingIntentModel()
    service = seeded_client.app.state.container.order_workflows
    service._model = model
    service._model_mode = "live"
    request = WorkflowStartRequest(
        message="刹车片补货，7天内到货", request_id="intent-budget-idempotency",
    )
    from backend.app.contracts.common import RequestContext
    ctx = RequestContext(owner_id="local-owner", request_id=request.request_id)
    first = seeded_client.portal.call(lambda: service.start(request, ctx))
    second = seeded_client.portal.call(lambda: service.start(request, ctx))
    assert first.id == second.id
    assert model.calls == 1
    persisted = seeded_client.portal.call(lambda: seeded_client.app.state.container.mongo.db["runs"].find_one({"_id": first.id}))
    assert persisted["model_calls"] == 1
    from backend.app.contracts.order_workflow import DraftPrepareRequest
    changed = request.model_copy(update={"draft": DraftPrepareRequest(part_ids=["P001"], warehouse_id="W01")})
    with pytest.raises(Exception) as error:
        seeded_client.portal.call(lambda: service.start(changed, ctx))
    assert "different payload" in str(error.value)
    assert model.calls == 1
