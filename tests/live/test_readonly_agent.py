"""P03-A06: fixed three real-model questions, three attempts each, plus DB fact checks."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from backend.app.config import load_settings
from backend.app.repositories.mongo import MongoResources
from scripts.live_acceptance import validate_live_run

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_MODEL") != "1" or not load_settings().model_configured,
    reason="live model not configured or not explicitly enabled",
)

QUESTIONS = [
    "哪些零件要补货？只看W01。",
    "刹车片要求7天内到货，推荐哪家？",
    "P003买哪家的最便宜？",
]


def parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        data = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
        if data:
            events.append(json.loads("\n".join(data)))
    return events


async def _database_facts() -> dict:
    settings = load_settings()
    if not settings.mongodb_database.startswith("technologyagent_test_"):
        raise AssertionError("live acceptance requires an isolated technologyagent_test_* database")
    mongo = await MongoResources.open(settings)
    try:
        inventory = await mongo.db["inventories"].find_one({"_id": "I001"})
        quote = await mongo.db["quotes"].find_one({"_id": "Q01"})
        p003_quote = await mongo.db["quotes"].find_one({"_id": "Q06"})
        assert inventory and quote and p003_quote, "live acceptance database does not contain P03 verification seed rows"
        shortage = max(0, inventory["target_stock"] - (inventory["on_hand"] - inventory["reserved"] + inventory["inbound"]))
        return {
            "inventory_id": inventory["_id"], "part_id": inventory["part_id"],
            "warehouse_id": inventory["warehouse_id"], "shortage": shortage,
            "quote_id": quote["_id"], "supplier_id": quote["supplier_id"],
            "lead_days": quote["lead_days"], "preview_total_cents": quote["unit_price_cents"] * shortage,
            "p003_quote_id": p003_quote["_id"], "p003_quote_expired": p003_quote["valid_until"] < datetime.now(timezone.utc),
        }
    finally:
        await mongo.close()


def test_live_readonly_three_questions_three_times():
    import asyncio

    base = os.environ.get("LIVE_API_URL", "http://127.0.0.1:8030")
    settings = load_settings()
    secret = settings.model_api_key.get_secret_value() if settings.model_api_key else ""
    db_facts = asyncio.run(_database_facts())
    assert db_facts["shortage"] == 55 and db_facts["preview_total_cents"] == 66000
    assert db_facts["p003_quote_expired"] is True
    trace: list[dict] = []
    passed_results: list[bool] = []
    with httpx.Client(base_url=base, timeout=210) as client:
        session = client.post("/api/session/local")
        assert session.status_code == 200, "local session could not be created"
        for question_index, question in enumerate(QUESTIONS):
            for attempt in range(1, 4):
                started_at = datetime.now(timezone.utc).isoformat()
                request_id = f"p03-live-{int(time.time() * 1000)}-{question_index}-{attempt}"
                item: dict = {
                    "question_index": question_index, "question": question, "attempt": attempt,
                    "request_id": request_id, "model_mode_expected": "live", "model_name": settings.model_name,
                    "started_at": started_at, "db_facts": db_facts,
                }
                try:
                    response = client.post("/api/chat/stream", json={"message": question, "request_id": request_id})
                    item["http_status"] = response.status_code
                    events = parse_sse(response.text) if response.status_code == 200 else []
                    passed, reasons = validate_live_run(events, question_index)
                    event_rows = [
                        {
                            "type": event.get("type"), "seq": event.get("seq"), "run_id": event.get("run_id"),
                            "payload": event.get("payload", {}),
                        }
                        for event in events
                    ]
                    def redact(value):
                        if isinstance(value, dict):
                            return {
                                key: "[redacted]" if any(term in key.lower() for term in ("api_key", "authorization", "token", "secret")) else redact(item_value)
                                for key, item_value in value.items()
                            }
                        if isinstance(value, list):
                            return [redact(item_value) for item_value in value]
                        if isinstance(value, str) and secret:
                            return value.replace(secret, "[redacted]")
                        return value
                    item["events"] = redact(event_rows)
                    item["passed"] = passed
                    item["reasons"] = reasons
                except Exception as exc:  # preserve each failed attempt in the trace
                    item["passed"] = False
                    item["reasons"] = [f"{type(exc).__name__}: {exc}"]
                item["finished_at"] = datetime.now(timezone.utc).isoformat()
                trace.append(item)
                passed_results.append(bool(item["passed"]))
    path = Path(".runtime/live/p03-readonly.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert len(trace) == 9, f"expected 9 live traces, got {len(trace)}; see {path}"
    assert all(passed_results), f"live acceptance passed {sum(passed_results)}/9; see {path}"
