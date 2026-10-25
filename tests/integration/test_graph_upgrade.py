"""P07-T01: capture a real P06 v1 approval checkpoint before graph routing changes."""

from pathlib import Path

from bson import json_util
from pymongo import MongoClient


FIXTURE = Path(__file__).parents[1] / "fixtures" / "p07-v1-pending-approval.json"


def _restore_preupgrade_checkpoint(client, db):
    snapshot = json_util.loads(FIXTURE.read_text(encoding="utf-8"))
    assert snapshot["provenance"]["created_before_p07_graph_upgrade"] is True
    assert snapshot["provenance"]["source_commit"] == "95740ef7c589ac007a794ec9682654f6e55ef2f0"
    assert snapshot["provenance"]["graph_version"] == "v1"
    for collection, documents in snapshot["collections"].items():
        # The integration fixture starts from seeded catalog facts. Add only this
        # historical run's records, avoiding duplicates for the seeded drafts.
        for document in documents:
            if collection == "drafts" and document["_id"] in {"D001", "D002"}:
                continue
            db[collection].insert_one(document)
    return snapshot

def test_preupgrade_v1_approval_checkpoint_resumes_once_after_upgrade(seeded_client):
    container = seeded_client.app.state.container
    client = MongoClient(container.settings.mongodb_uri.get_secret_value())
    db = client[container.settings.mongodb_database]
    try:
        snapshot = _restore_preupgrade_checkpoint(client, db)
        run_doc = snapshot["collections"]["runs"][0]
        run_id = run_doc["_id"]
        before = seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"]
        assert before == 2
        assert seeded_client.get(f"/api/runs/{run_id}").json()["data"]["pending_interrupt"]["kind"] == "approval"

        pending = run_doc["pending_interrupt"]
        decision = {
            "interrupt_id": pending["interrupt_id"], "decision": "approve",
            "expected_version": pending["version"], "payload": {},
            "idempotency_key": "p07-v1-approval-once",
        }
        first = seeded_client.post(f"/api/runs/{run_id}/resume", json=decision)
        assert first.status_code == 200, first.text
        assert first.json()["data"]["status"] == "completed"
        assert db["runs"].find_one({"_id": run_id})["graph_version"] == "v1"
        assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before + 1

        replay = seeded_client.post(f"/api/runs/{run_id}/resume", json=decision)
        assert replay.status_code == 200, replay.text
        assert replay.json()["data"]["status"] == "completed"
        assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before + 1
    finally:
        client.close()


def test_new_order_run_is_persistently_routed_to_v2(seeded_client):
    response = seeded_client.post("/api/order-workflows", json={
        "message": "补货 P001 并准备订单",
        "request_id": "p07-new-order-v2",
        "draft": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
    })
    assert response.status_code == 200, response.text
    run = response.json()["data"]
    assert run["graph_version"] == "v2"
    container = seeded_client.app.state.container
    client = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        key = f"p07:v2:{run['thread_id']}:{run['id']}"
        assert client[container.settings.mongodb_database]["lg_checkpoints"].count_documents({
            "thread_id": key, "checkpoint_ns": "",
        }) > 0
    finally:
        client.close()
