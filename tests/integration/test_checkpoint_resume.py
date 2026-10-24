"""P04 interrupt checkpoint survives the request boundary and resumes the same run."""


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
