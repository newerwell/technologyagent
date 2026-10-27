"""P09-F12: real model applies a persisted preference and returns proven facts."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from pymongo import MongoClient

from backend.app.config import load_settings
from scripts.live_acceptance import validate_preference_attempt


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


def _data(response: httpx.Response) -> dict:
    if response.status_code != 200:
        raise AssertionError(f"HTTP {response.status_code}")
    body = response.json()
    return body.get("data", body)


def _business_snapshot(db) -> dict:
    inventory = db["inventories"].find_one({"_id": "I001"})
    if not inventory:
        raise AssertionError("P09 live seed is missing inventory I001")
    return {
        "orders": db["orders"].count_documents({}),
        "inventory": {key: inventory.get(key) for key in (
            "_id", "part_id", "warehouse_id", "on_hand", "reserved", "inbound",
            "safety_stock", "target_stock", "version",
        )},
    }


def _run_id(events: list[dict]) -> tuple[str | None, str | None]:
    started = [event for event in events if event.get("type") == "run_started"]
    if len(started) != 1:
        return None, None
    event = started[0]
    return event.get("run_id"), event.get("thread_id")


def _safe(value, secret: str):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(marker in key.lower() for marker in ("api_key", "authorization", "access_token", "secret", "password"))
            else _safe(item, secret)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_safe(item, secret) for item in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, "[REDACTED]")
    return value


def _write_attempt(path: Path, record: dict, secret: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(_safe(record, secret), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temp.replace(path)


def test_live_preference_is_used_by_a_followup_run_and_preserved():
    settings = load_settings()
    assert settings.mongodb_database.startswith("technologyagent_test_"), "live acceptance requires an isolated test database"
    mongo = MongoClient(settings.mongodb_uri.get_secret_value())
    db = mongo[settings.mongodb_database]
    base = os.environ.get("LIVE_API_URL", "http://127.0.0.1:8030")
    secret = settings.model_api_key.get_secret_value() if settings.model_api_key else ""
    batch_id = re.sub(r"[^A-Za-z0-9_-]", "", os.environ.get("P09_BATCH_ID", ""))[:80]
    if not batch_id:
        batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]
    label = re.sub(r"[^A-Za-z0-9_-]", "", os.environ.get("P09_ATTEMPT_LABEL", "manual"))[:80]
    out_dir = Path(".runtime/live/p09/attempts") / batch_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"F12-{label}.json"
    suffix = 1
    while path.exists():
        path = out_dir / f"F12-{label}-{suffix}.json"
        suffix += 1

    attempts: list[dict] = []
    with httpx.Client(base_url=base, timeout=240) as api:
        for attempt_index in range(1, 4):
            record = {
                "batch_id": batch_id,
                "attempt": attempt_index,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "model_mode_expected": "live",
                "model_name": settings.model_name,
                "database": settings.mongodb_database,
                "status": "running",
            }
            _write_attempt(path, {"attempts": attempts + [record]}, secret)
            try:
                session = api.post("/api/session/local")
                if session.status_code != 200:
                    raise AssertionError(f"could not create local session: HTTP {session.status_code}")
                cleared = api.delete("/api/preferences/default_warehouse")
                if cleared.status_code not in {200, 404}:
                    raise AssertionError(f"could not isolate preference state: HTTP {cleared.status_code}")
                record["preferences_before"] = _data(api.get("/api/preferences"))
                record["database_before"] = _business_snapshot(db)

                remember = api.post("/api/chat/stream", json={
                    "message": "记住默认仓库W01", "request_id": f"p09-pref-set-{time.time_ns()}"})
                record["remember_http_status"] = remember.status_code
                record["remember_events"] = _events(remember) if remember.status_code == 200 else []
                record["preferences_after_remember"] = _data(api.get("/api/preferences"))
                remember_id, _remember_thread = _run_id(record["remember_events"])
                record["remember_run"] = _data(api.get(f"/api/runs/{remember_id}")) if remember_id else None

                followup = api.post("/api/chat/stream", json={
                    "message": "P001当前目标库存缺口是多少套？请只回答P001缺口。",
                    "request_id": f"p09-pref-query-{time.time_ns()}"})
                record["query_http_status"] = followup.status_code
                record["query_events"] = _events(followup) if followup.status_code == 200 else []
                record["preferences_after_query"] = _data(api.get("/api/preferences"))
                query_id, thread_id = _run_id(record["query_events"])
                record["query_run"] = _data(api.get(f"/api/runs/{query_id}")) if query_id else None
                record["persisted_query_events"] = _data(api.get(
                    f"/api/runs/{query_id}/events", params={"after_seq": 0})) if query_id else []
                conversation = _data(api.get(f"/api/conversations/{thread_id}")) if thread_id else {}
                record["assistant_messages"] = [message for message in conversation.get("messages", [])
                    if message.get("run_id") == query_id and message.get("role") == "assistant"]
                record["answer"] = record["assistant_messages"][-1].get("content", "") if record["assistant_messages"] else ""
                record["database_after"] = _business_snapshot(db)
                record["issues"] = validate_preference_attempt({
                    "remember_events": record.get("remember_events"),
                    "query_events": record.get("query_events"),
                    "remember_run": record.get("remember_run"),
                    "query_run": record.get("query_run"),
                    "remember_preferences": record.get("preferences_after_remember"),
                    "query_preferences": record.get("preferences_after_query"),
                    "database_before": record.get("database_before"),
                    "database_after": record.get("database_after"),
                    "answer": record.get("answer"),
                })
                if record["remember_http_status"] != 200 or record["query_http_status"] != 200:
                    record["issues"].append("remember/query HTTP request did not return 200")
                event_seqs = [event.get("seq") for event in record["query_events"]]
                persisted_seqs = [event.get("seq") for event in record["persisted_query_events"]]
                if event_seqs != persisted_seqs:
                    record["issues"].append("persisted query events differ from the response stream")
                record["passed"] = not record["issues"]
                record["status"] = "passed" if record["passed"] else "failed"
            except Exception as exc:  # keep the failed attempt, then continue to all three
                message = str(exc)
                if secret:
                    message = message.replace(secret, "[REDACTED]")
                record["error"] = f"{type(exc).__name__}: {message[:1000]}"
                record["issues"] = [record["error"]]
                record["passed"] = False
                record["status"] = "failed"
            finally:
                record["finished_at"] = datetime.now(timezone.utc).isoformat()
                attempts.append(record)
                _write_attempt(path, {"attempts": attempts}, secret)
    mongo.close()
    assert len(attempts) == 3, f"expected 3 complete preference attempts; evidence: {path}"
    assert all(item.get("passed") is True for item in attempts), f"preference attempts failed; evidence: {path}"
