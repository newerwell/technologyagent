"""HTTP regression for the complete proposal -> decision -> execution path."""

from pymongo import MongoClient


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
