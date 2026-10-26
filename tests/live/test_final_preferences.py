"""P09-F12: real model respects a persisted preference in a separate run."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from pymongo import MongoClient

from backend.app.config import load_settings


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_MODEL") != "1" or not load_settings().model_configured
    or load_settings().model_mode != "live",
    reason="P09 preference validation requires explicit live model configuration",
)


def _events(response: httpx.Response) -> list[dict]:
    output = []
    for block in response.text.replace("\r\n", "\n").split("\n\n"):
        data = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
        if data:
            output.append(json.loads("\n".join(data)))
    return output


def test_live_preference_is_used_by_a_followup_run_and_preserved():
    settings = load_settings()
    assert settings.mongodb_database.startswith("technologyagent_test_")
    mongo = MongoClient(settings.mongodb_uri.get_secret_value())
    db = mongo[settings.mongodb_database]
    base = os.environ.get("LIVE_API_URL", "http://127.0.0.1:8030")
    attempts = []
    try:
        with httpx.Client(base_url=base, timeout=240) as api:
            for attempt in range(1, 4):
                started = datetime.now(timezone.utc).isoformat()
                before = {"orders": db["orders"].count_documents({}),
                          "inventory": db["inventories"].find_one({"_id": "I001"})}
                session = api.post("/api/session/local")
                assert session.status_code == 200, session.text
                remember = api.post("/api/chat/stream", json={
                    "message": "记住默认仓库W01", "request_id": f"p09-pref-set-{time.time_ns()}"})
                assert remember.status_code == 200, remember.text
                remembered_events = _events(remember)
                followup = api.post("/api/chat/stream", json={
                    "message": "P001还需要补货多少件？", "request_id": f"p09-pref-query-{time.time_ns()}"})
                assert followup.status_code == 200, followup.text
                query_events = _events(followup)
                started_events = [event for event in query_events if event["type"] == "tool_started"]
                assert any(event["payload"].get("args_summary", {}).get("warehouse_id") == "W01"
                           for event in started_events), "persisted default warehouse was not applied"
                after = {"orders": db["orders"].count_documents({}),
                         "inventory": db["inventories"].find_one({"_id": "I001"})}
                assert before == after, "preference queries changed business facts"
                attempts.append({"attempt": attempt, "started_at": started,
                                 "model_mode": "live", "database_before": before,
                                 "remember_event_types": [event["type"] for event in remembered_events],
                                 "query_events": query_events, "database_after": after, "passed": True})
    finally:
        mongo.close()
        label = os.environ.get("P09_ATTEMPT_LABEL", "manual")
        safe_label = "".join(character for character in label if character.isalnum() or character in "-_")[:100]
        path = Path(".runtime/live/p09") / f"F12-preferences-{safe_label}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(attempts, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    assert len(attempts) == 3
