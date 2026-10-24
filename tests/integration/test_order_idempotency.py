"""P04 事务与幂等关键边界。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient
from backend.app.contracts.common import AppError


def _approved_draft(client):
    prepared = client.post("/api/drafts", json={
        "part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7,
    })
    assert prepared.status_code == 200, prepared.text
    draft = prepared.json()["data"]["drafts"][0]
    requested = client.post(f"/api/drafts/{draft['id']}/approval", json={"run_id": "run_test"})
    assert requested.status_code == 200, requested.text
    approval_id = requested.json()["data"]["approval_id"]
    resolved = client.post(f"/api/approvals/{approval_id}/resolve", json={
        "interrupt_id": "intr_test", "decision": "approve", "expected_version": 1,
        "idempotency_key": "approval-test",
    })
    assert resolved.status_code == 200, resolved.text
    return draft, approval_id


def test_approved_order_is_atomic_and_idempotent(seeded_client):
    draft, approval_id = _approved_draft(seeded_client)
    before = seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"]
    body = {"draft_id": draft["id"], "approval_id": approval_id, "idempotency_key": "create-55"}
    first = seeded_client.post("/api/orders/create", json=body)
    assert first.status_code == 200, first.text
    second = seeded_client.post("/api/orders/create", json=body)
    assert second.status_code == 200, second.text
    order1 = first.json()["data"]["order"]
    order2 = second.json()["data"]["order"]
    assert order1["id"] == order2["id"]
    assert order1["total_cents"] == 66000
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before + 1
    inventory = seeded_client.get("/api/inventory?warehouse_id=W01&part_name=刹车片").json()["data"]["records"]
    p001 = next(record for record in inventory if record["part_id"] == "P001")
    assert (p001["on_hand"], p001["inbound"], p001["projected"]) == (20, 65, 80)


def test_same_key_different_payload_is_conflict(seeded_client):
    draft, approval_id = _approved_draft(seeded_client)
    body = {"draft_id": draft["id"], "approval_id": approval_id, "idempotency_key": "same-key"}
    first = seeded_client.post("/api/orders/create", json=body)
    assert first.status_code == 200, first.text
    changed = {**body, "draft_id": "different-draft"}
    response = seeded_client.post("/api/orders/create", json=changed)
    assert response.status_code == 409


def test_concurrent_duplicate_requests_converge_to_one_order(seeded_client):
    draft, approval_id = _approved_draft(seeded_client)
    body = {"draft_id": draft["id"], "approval_id": approval_id, "idempotency_key": "parallel-key"}
    def submit(_):
        return seeded_client.post("/api/orders/create", json=body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, range(2)))
    assert all(response.status_code == 200 for response in responses), [r.text for r in responses]
    ids = [r.json()["data"]["order"]["id"] for r in responses]
    assert ids[0] == ids[1]
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == 3


def test_inventory_version_change_requires_new_confirmation(seeded_client):
    draft, approval_id = _approved_draft(seeded_client)
    container = seeded_client.app.state.container
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        sync[container.settings.mongodb_database]["inventories"].update_one({"_id": "I001"}, {"$inc": {"version": 1}})
    finally:
        sync.close()
    response = seeded_client.post("/api/orders/create", json={
        "draft_id": draft["id"], "approval_id": approval_id, "idempotency_key": "stale-stock",
    })
    assert response.status_code == 409
    assert seeded_client.get(f"/api/drafts/{draft['id']}").json()["data"]["state"] == "superseded"
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == 2


def test_quote_change_requires_new_confirmation_even_when_quote_id_is_unchanged(seeded_client):
    draft, approval_id = _approved_draft(seeded_client)
    container = seeded_client.app.state.container
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        sync[container.settings.mongodb_database]["quotes"].update_one(
            {"_id": "Q01"}, {"$set": {"lead_days": 8}}
        )
    finally:
        sync.close()
    response = seeded_client.post("/api/orders/create", json={
        "draft_id": draft["id"], "approval_id": approval_id, "idempotency_key": "stale-quote",
    })
    assert response.status_code == 409
    assert seeded_client.get(f"/api/drafts/{draft['id']}").json()["data"]["state"] == "superseded"
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == 2
    inventory = seeded_client.get("/api/inventory?warehouse_id=W01&part_name=刹车片").json()["data"]["records"]
    p001 = next(record for record in inventory if record["part_id"] == "P001")
    assert (p001["on_hand"], p001["inbound"]) == (20, 10)


def test_crash_inside_transaction_rolls_back_and_expired_lease_can_reconcile(seeded_client):
    draft, approval_id = _approved_draft(seeded_client)
    container = seeded_client.app.state.container
    container.mutations._fault_hook = lambda point: (_ for _ in ()).throw(AppError("SIMULATED_CRASH", "crash", http_status=500)) if point == "after_order_write" else None
    body = {"draft_id": draft["id"], "approval_id": approval_id, "idempotency_key": "crash-tx"}
    failed = seeded_client.post("/api/orders/create", json=body)
    assert failed.status_code == 500
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == 2
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        inv = sync[container.settings.mongodb_database]["inventories"].find_one({"_id": "I001"})
    finally:
        sync.close()
    assert (inv["on_hand"], inv["inbound"]) == (20, 10)
    container.mutations._fault_hook = None
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        sync[container.settings.mongodb_database]["operations"].update_one(
            {"owner_id": "local-owner", "idempotency_key": "crash-tx"},
            {"$set": {"lease_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}},
        )
    finally:
        sync.close()
    recovered = seeded_client.post("/api/orders/create", json=body)
    assert recovered.status_code == 200, recovered.text
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == 3


def test_committed_but_lost_response_returns_original_order(seeded_client):
    draft, approval_id = _approved_draft(seeded_client)
    container = seeded_client.app.state.container
    container.mutations._fault_hook = lambda point: (_ for _ in ()).throw(AppError("SIMULATED_CRASH", "response lost", http_status=500)) if point == "after_commit_before_response" else None
    body = {"draft_id": draft["id"], "approval_id": approval_id, "idempotency_key": "lost-response"}
    failed_response = seeded_client.post("/api/orders/create", json=body)
    assert failed_response.status_code == 500
    container.mutations._fault_hook = None
    retry = seeded_client.post("/api/orders/create", json=body)
    assert retry.status_code == 200, retry.text
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == 3
    operation_id = retry.json()["data"]["operation_id"]
    checked = seeded_client.post(f"/api/operations/{operation_id}/reconcile")
    assert checked.status_code == 200, checked.text
    assert checked.json()["data"]["status"] == "succeeded"
    assert checked.json()["data"]["result"]["order"]["id"] == retry.json()["data"]["order"]["id"]


def test_reject_keeps_draft_and_creates_no_order(seeded_client):
    prepared = seeded_client.post("/api/drafts", json={
        "part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7,
    }).json()["data"]["drafts"][0]
    approval = seeded_client.post(f"/api/drafts/{prepared['id']}/approval", json={"run_id": "reject-run"}).json()["data"]["approval_id"]
    before = seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"]
    rejected = seeded_client.post(f"/api/approvals/{approval}/resolve", json={
        "interrupt_id": "reject-int", "decision": "reject", "expected_version": 1,
        "idempotency_key": "reject-key",
    })
    assert rejected.status_code == 200, rejected.text
    assert seeded_client.get(f"/api/drafts/{prepared['id']}").json()["data"]["state"] == "rejected"
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before


def test_edit_supersedes_old_approval_and_reprices(seeded_client):
    prepared = seeded_client.post("/api/drafts", json={
        "part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7,
    }).json()["data"]["drafts"][0]
    approval = seeded_client.post(f"/api/drafts/{prepared['id']}/approval", json={"run_id": "edit-run"}).json()["data"]["approval_id"]
    edited = seeded_client.patch(f"/api/drafts/{prepared['id']}", json={
        "expected_version": 1, "items": [{"part_id": "P001", "quote_id": "Q01", "quantity": 60}],
    })
    assert edited.status_code == 200, edited.text
    assert (edited.json()["data"]["version"], edited.json()["data"]["total_cents"]) == (2, 72000)
    stale = seeded_client.post(f"/api/approvals/{approval}/resolve", json={
        "interrupt_id": "old", "decision": "approve", "expected_version": 1,
        "idempotency_key": "old-approval",
    })
    assert stale.status_code == 409


def test_direct_order_create_without_approval_is_forbidden(seeded_client):
    draft = seeded_client.post("/api/drafts", json={
        "part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7,
    }).json()["data"]["drafts"][0]
    response = seeded_client.post("/api/orders/create", json={
        "draft_id": draft["id"], "approval_id": "missing-approval", "idempotency_key": "unapproved",
    })
    assert response.status_code == 403
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == 2
    container = seeded_client.app.state.container
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        operations = sync[container.settings.mongodb_database]["operations"]
        assert operations.count_documents({"idempotency_key": "unapproved"}) == 0
    finally:
        sync.close()


def test_crash_after_claim_is_recoverable_after_lease_expiry(seeded_client):
    draft, approval_id = _approved_draft(seeded_client)
    container = seeded_client.app.state.container
    container.mutations._fault_hook = lambda point: (_ for _ in ()).throw(AppError("SIMULATED_CRASH", "crash", http_status=500)) if point == "after_claim" else None
    body = {"draft_id": draft["id"], "approval_id": approval_id, "idempotency_key": "crash-claim"}
    failed = seeded_client.post("/api/orders/create", json=body)
    assert failed.status_code == 500
    container.mutations._fault_hook = None
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        sync[container.settings.mongodb_database]["operations"].update_one(
            {"owner_id": "local-owner", "idempotency_key": "crash-claim"},
            {"$set": {"lease_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}},
        )
        operation = sync[container.settings.mongodb_database]["operations"].find_one(
            {"owner_id": "local-owner", "idempotency_key": "crash-claim"}
        )
    finally:
        sync.close()
    reconciliation = seeded_client.post(f"/api/operations/{operation['_id']}/reconcile")
    assert reconciliation.status_code == 200, reconciliation.text
    assert reconciliation.json()["data"]["status"] == "retryable"
    recovered = seeded_client.post("/api/orders/create", json=body)
    assert recovered.status_code == 200, recovered.text
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == 3
