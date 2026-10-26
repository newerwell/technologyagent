"""HTTP regression for the complete proposal -> decision -> execution path."""

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
