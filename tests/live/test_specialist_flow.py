"""P07真实委派：分析专家出具报告，再由订单专家进入同run审批。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pymongo import MongoClient

from backend.app.config import load_settings


QUESTION = "分析 W01 的 P001 补货需求并生成报告，然后准备 P001 在 W01 的订单，7天内到货。"


def _parse_events(text: str) -> list[dict]:
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        payload = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
        if payload:
            events.append(json.loads("\n".join(payload)))
    return events


def test_live_analysis_then_order_uses_specialists_and_waits_on_original_run():
    settings = load_settings()
    assert os.environ.get("RUN_LIVE_MODEL") == "1", "P07 live requires explicit RUN_LIVE_MODEL=1"
    assert settings.model_mode == "live" and settings.model_configured, "P07 live needs a configured live model"
    assert settings.mongodb_database.startswith("technologyagent_test_"), "P07 live requires an isolated test database"

    mongo = MongoClient(settings.mongodb_uri.get_secret_value())
    db = mongo[settings.mongodb_database]
    before = {
        "orders": db["orders"].count_documents({}),
        "operations": db["operations"].count_documents({"action": "order_create"}),
        "inventory": db["inventories"].find_one({"_id": "I001"}),
        "artifacts": db["artifacts"].count_documents({}),
    }
    assert before["inventory"] and (before["inventory"]["on_hand"], before["inventory"]["inbound"]) == (20, 10)
    trace: dict = {"stage": "P07", "model_name": settings.model_name,
                   "database": settings.mongodb_database, "question": QUESTION,
                   "started_at": datetime.now(timezone.utc).isoformat(), "attempts": []}
    trace["database_before"] = {
        "orders": before["orders"], "order_create_operations": before["operations"],
        "inventory": {"on_hand": before["inventory"]["on_hand"], "inbound": before["inventory"]["inbound"]},
        "artifact_count": before["artifacts"],
    }
    failure: BaseException | None = None
    try:
        base = os.environ.get("LIVE_API_URL", "http://127.0.0.1:8030")
        with httpx.Client(base_url=base, timeout=240) as api:
            session = api.post("/api/session/local")
            assert session.status_code == 200, session.text
            response = api.post("/api/chat/stream", json={
                "message": QUESTION, "request_id": "p07-live-" + os.urandom(8).hex(),
            })
            assert response.status_code == 200, response.text
            events = _parse_events(response.text)
            trace["attempts"].append({"sse_events": events})
            assert events and events[-1]["type"] == "stream_end"
            run_id, thread_id = events[0]["run_id"], events[0]["thread_id"]
            run_response = api.get(f"/api/runs/{run_id}")
            assert run_response.status_code == 200, run_response.text
            run = run_response.json()["data"]
            trace["run"] = run
            assert events[0]["payload"]["model_mode"] == "live"
            assert run["graph_version"] == "v2"
            if run["status"] == "waiting_input" and run["pending_interrupt"]["kind"] == "supplement":
                supplement = api.post(f"/api/runs/{run_id}/resume", json={
                    "interrupt_id": run["pending_interrupt"]["interrupt_id"],
                    "decision": "supplement", "expected_version": None,
                    "payload": {"warehouse_id": "W01"},
                    "idempotency_key": "p07-live-supplement-" + run_id,
                })
                assert supplement.status_code == 200, supplement.text
                run = supplement.json()["data"]
                trace["supplement"] = run
            assert run["status"] == "waiting_input", run
            assert run["pending_interrupt"]["kind"] == "approval", run
            assert run["thread_id"] == thread_id
            assert {item["name"] for item in run["specialist_trace"]} >= {"analyst", "order"}
            assert {item["id"] for item in run["skill_manifest"]} >= {
                "inventory-replenishment", "procurement-report", "supplier-comparison",
            }
            assert any(event["type"] == "tool_started" and event["payload"]["actor"] == "analyst" for event in events)
            assert any(event["type"] == "artifact_ready" for event in events)
            pending = run["pending_interrupt"]
            draft_response = api.get(f"/api/drafts/{pending['draft_id']}")
            assert draft_response.status_code == 200, draft_response.text
            draft = draft_response.json()["data"]
            trace["draft"] = draft
            assert draft["warehouse_id"] == "W01"
            assert draft["items"]
            assert db["orders"].count_documents({}) == before["orders"]
            assert db["operations"].count_documents({"action": "order_create"}) == before["operations"]
            current_inventory = db["inventories"].find_one({"_id": "I001"})
            assert (current_inventory["on_hand"], current_inventory["inbound"]) == (20, 10)
            trace["database_after"] = {
                "orders": db["orders"].count_documents({}),
                "operations": db["operations"].count_documents({"action": "order_create"}),
                "inventory": {"on_hand": current_inventory["on_hand"], "inbound": current_inventory["inbound"]},
                "artifact_count": db["artifacts"].count_documents({}),
            }
    except BaseException as exc:
        failure = exc
        trace["failure"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        trace["finished_at"] = datetime.now(timezone.utc).isoformat()
        path = Path(".runtime/reports") / f"P07-live-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(trace, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        mongo.close()
    if failure is not None:
        raise failure
