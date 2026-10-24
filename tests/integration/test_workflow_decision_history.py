"""Resume decisions remain replayable after later decisions complete a run."""

from pymongo import MongoClient


def test_old_edit_decision_replays_its_result_and_persists_warehouse_patch(seeded_client):
    started = seeded_client.post("/api/order-workflows", json={
        "message": "创建P001在W01的订单，确认前改到W02。",
        "request_id": "decision-history-edit-replay",
        "draft": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
    })
    assert started.status_code == 200, started.text
    run = started.json()["data"]
    pending = run["pending_interrupt"]
    edit_request = {
        "interrupt_id": pending["interrupt_id"], "decision": "edit",
        "expected_version": pending["version"], "payload": {
            "warehouse_id": "W02",
            "items": [{"part_id": "P001", "quote_id": "Q01", "quantity": 55}],
        }, "idempotency_key": "decision-history-edit-v1",
    }
    edited = seeded_client.post(f"/api/runs/{run['id']}/resume", json=edit_request)
    assert edited.status_code == 200, edited.text
    edit_result = edited.json()["data"]
    assert edit_result["status"] == "waiting_input"
    assert edit_result["pending_interrupt"]["version"] == 2

    mongo = MongoClient(seeded_client.app.state.settings.mongodb_uri.get_secret_value())
    try:
        db = mongo[seeded_client.app.state.settings.mongodb_database]
        draft = db["drafts"].find_one({"workflow_run_id": run["id"]})
        assert draft["warehouse_id"] == "W02"
    finally:
        mongo.close()

    approved = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": edit_result["pending_interrupt"]["interrupt_id"],
        "decision": "approve", "expected_version": 2,
        "payload": {}, "idempotency_key": "decision-history-approve-v2",
    })
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "completed"
    order_count = seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"]

    replay = seeded_client.post(f"/api/runs/{run['id']}/resume", json=edit_request)
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["status"] == "waiting_input"
    assert replay.json()["data"]["pending_interrupt"]["version"] == 2
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == order_count

    changed = {**edit_request, "payload": {**edit_request["payload"], "warehouse_id": "W01"}}
    conflict = seeded_client.post(f"/api/runs/{run['id']}/resume", json=changed)
    assert conflict.status_code == 409
