"""P04 live model acceptance; opt in, isolated test DB, and save full redacted trace."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from pymongo import MongoClient

from backend.app.config import load_settings

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_MODEL") != "1" or not load_settings().model_configured,
    reason="live model not configured or not explicitly enabled",
)


def test_live_model_order_draft_edit_restart_ready_approve_and_db_facts():
    settings = load_settings()
    if not settings.mongodb_database.startswith("technologyagent_test_"):
        pytest.fail("P04 live acceptance requires technologyagent_test_* database")
    secret = settings.model_api_key.get_secret_value() if settings.model_api_key else ""
    trace: dict = {"model_name": settings.model_name, "database": settings.mongodb_database,
                   "started_at": datetime.now(timezone.utc).isoformat(), "steps": []}
    acceptance_id = os.urandom(8).hex()
    client = MongoClient(settings.mongodb_uri.get_secret_value())
    db = client[settings.mongodb_database]
    before = {
        "order_count": db["orders"].count_documents({}),
        "inventory": db["inventories"].find_one({"_id": "I001"}),
    }
    assert before["inventory"] is not None
    assert (before["inventory"]["on_hand"], before["inventory"]["inbound"]) == (20, 10)
    base = os.environ.get("LIVE_API_URL", "http://127.0.0.1:8030")
    try:
        with httpx.Client(base_url=base, timeout=90) as api:
            session = api.post("/api/session/local")
            assert session.status_code == 200, session.text
            started = api.post("/api/order-workflows", json={
                "message": "刹车片补到目标库存，7天内到货，生成订单",
                "request_id": "p04-live-" + acceptance_id,
            })
            assert started.status_code == 200, started.text
            run = started.json()["data"]
            trace["steps"].append({"action": "start", "run": run})
            assert run["status"] == "waiting_input"
            assert run["pending_interrupt"]["kind"] == "supplement"
            start_events = api.get(f"/api/runs/{run['id']}/events", params={"after_seq": 0})
            assert start_events.status_code == 200, start_events.text
            assert any(event["type"] == "run_started" and event["payload"].get("model_mode") == "live"
                       for event in start_events.json()["data"])
            assert db["orders"].count_documents({}) == before["order_count"]

            supplemented = api.post(f"/api/runs/{run['id']}/resume", json={
                "interrupt_id": run["pending_interrupt"]["interrupt_id"], "decision": "supplement",
                "expected_version": None, "payload": {"warehouse_id": "W01"},
                "idempotency_key": f"p04-live-supplement-{acceptance_id}",
            })
            assert supplemented.status_code == 200, supplemented.text
            waiting = supplemented.json()["data"]
            assert db["orders"].count_documents({}) == before["order_count"]
            draft_id = waiting["pending_interrupt"]["draft_id"]
            draft = api.get(f"/api/drafts/{draft_id}").json()["data"]
            assert (draft["supplier_id"], draft["warehouse_id"], draft["items"][0]["quantity"], draft["total_cents"]) == ("S01", "W01", 55, 66000)
            trace["steps"].append({"action": "supplement", "run": waiting, "draft": draft})

            # A new HTTP request and a fresh graph instance exercise the persisted waiting checkpoint.
            refreshed = api.get(f"/api/runs/{run['id']}").json()["data"]
            assert refreshed["pending_interrupt"]["interrupt_id"] == waiting["pending_interrupt"]["interrupt_id"]
            approved = api.post(f"/api/runs/{run['id']}/resume", json={
                "interrupt_id": refreshed["pending_interrupt"]["interrupt_id"], "decision": "approve",
                "expected_version": 1, "payload": {}, "idempotency_key": f"p04-live-create-{acceptance_id}",
            })
            assert approved.status_code == 200, approved.text
            trace["steps"].append({"action": "approve", "run": approved.json()["data"]})
            events = api.get(f"/api/runs/{run['id']}/events", params={"after_seq": 0})
            assert events.status_code == 200, events.text
            trace["events"] = events.json()["data"]
            assert any(event["type"] == "run_finished" and event["payload"].get("status") == "completed"
                       for event in trace["events"])
            assert any(event["type"] == "stream_end" and event["payload"].get("reason") == "completed"
                       for event in trace["events"])
            after_inventory = db["inventories"].find_one({"_id": "I001"})
            after_count = db["orders"].count_documents({})
            assert after_count == before["order_count"] + 1
            assert after_inventory and (after_inventory["on_hand"], after_inventory["inbound"]) == (20, 65)
            order = db["orders"].find_one({"draft_id": draft_id})
            assert order and order["total_cents"] == 66000
            trace["database_before"] = {"order_count": before["order_count"], "inventory": before["inventory"]}
            trace["database_after"] = {"order_count": after_count, "inventory": after_inventory, "order": order}
    finally:
        client.close()
    if secret:
        text = json.dumps(trace, ensure_ascii=False, default=str)
        trace = json.loads(text.replace(secret, "[redacted]"))
    trace["finished_at"] = datetime.now(timezone.utc).isoformat()
    path = Path(".runtime/live/p04-order-workflow-attempts.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    attempts = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    attempts.append(trace)
    path.write_text(json.dumps(attempts, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
