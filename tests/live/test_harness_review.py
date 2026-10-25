"""P05真实模型库存回答的Harness事件、硬评审和DB只读核验。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from pymongo import MongoClient

from backend.app.config import load_settings
from scripts.live_acceptance import validate_live_run

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_MODEL") != "1" or not load_settings().model_configured
    or load_settings().model_mode != "live",
    reason="P05 live requires configured model and explicit RUN_LIVE_MODEL=1",
)


def test_live_inventory_answer_has_harness_and_no_database_mutation():
    settings = load_settings()
    if not settings.mongodb_database.startswith("technologyagent_test_"):
        pytest.fail("P05 live requires an isolated technologyagent_test_* database")
    secret = settings.model_api_key.get_secret_value() if settings.model_api_key else ""
    client = MongoClient(settings.mongodb_uri.get_secret_value())
    db = client[settings.mongodb_database]
    before = {
        "orders": db["orders"].count_documents({}),
        "inventory": db["inventories"].find_one({"_id": "I001"}),
    }
    assert before["inventory"] is not None
    base = os.environ.get("LIVE_API_URL", "http://127.0.0.1:8030")
    trace: dict = {"model_name": settings.model_name,
                   "question": "只用P001在W01的库存记录回答缺货件数，并注明数据来源。不要提及其他库存指标、记录或任何数字，也不要提出额外建议。",
                   "started_at": datetime.now(timezone.utc).isoformat(), "database_before": before}
    failure: BaseException | None = None
    try:
        with httpx.Client(base_url=base, timeout=180) as api:
            session = api.post("/api/session/local")
            assert session.status_code == 200, session.text
            response = api.post("/api/chat/stream", json={
                "message": trace["question"], "request_id": "p05-live-" + os.urandom(8).hex(),
            })
            assert response.status_code == 200, response.text
            events = []
            for block in response.text.replace("\r\n", "\n").split("\n\n"):
                data = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
                if data:
                    events.append(json.loads("\n".join(data)))
            trace["events"] = events
            phases = [event["payload"]["phase"] for event in events if event["type"] == "phase"]
            reviews = [event["payload"] for event in events if event["type"] == "review"]
            revision_count = reviews[-1]["revision_count"] if reviews else -1
            expected_phases = ["planning", "executing"]
            for _ in range(revision_count):
                expected_phases.extend(["reviewing", "executing"])
            expected_phases.extend(["reviewing", "result"])
            assert 0 <= revision_count <= 2
            assert phases == expected_phases, phases
            plan = [event["payload"] for event in events if event["type"] == "plan"]
            assert plan and any(
                item.get("status") == "done" and (item.get("evidence_refs") or item.get("query_evidence"))
                for item in plan[-1]["items"]
            )
            assert reviews and reviews[-1]["passed"] is True
            assert any(event["type"] == "token" for event in events)
            assert any(event["type"] == "run_finished" and event["payload"].get("status") == "completed"
                       for event in events)
            valid, reasons = validate_live_run(events, 0)
            assert valid, "P05 live trace failed the shared strict P03 fact gate: " + "; ".join(reasons)
            after = {"orders": db["orders"].count_documents({}),
                     "inventory": db["inventories"].find_one({"_id": "I001"})}
            assert before == after, "read-only live Harness changed database facts"
            trace["database_after"] = after
    except BaseException as exc:
        failure = exc
        trace["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        if "database_after" not in trace:
            trace["database_after_failure"] = {
                "orders": db["orders"].count_documents({}),
                "inventory": db["inventories"].find_one({"_id": "I001"}),
            }
        client.close()
    if secret:
        trace_text = json.dumps(trace, ensure_ascii=False, default=str).replace(secret, "[redacted]")
        trace = json.loads(trace_text)
    trace["finished_at"] = datetime.now(timezone.utc).isoformat()
    path = Path(".runtime/live/p05-harness-attempts.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    previous.append(trace)
    path.write_text(json.dumps(previous, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    if failure is not None:
        raise failure
