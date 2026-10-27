"""P05-A04: an injected first omission is repaired by the configured live model only in prose."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from backend.app.config import load_settings
from backend.app.contracts.workflow import ReviewCheck, ReviewResult
from backend.app.integrations.model import build_model
from backend.app.main import create_app
from backend.app.services import order_workflows as workflows
from backend.app.services.order_workflows import _order_answer_fact_check

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_MODEL") != "1" or not load_settings().model_configured
    or load_settings().model_mode != "live",
    reason="P05 live A04 requires configured MODEL_MODE=live and explicit RUN_LIVE_MODEL=1",
)


def test_live_order_answer_revision_a04_never_replays_order(monkeypatch):
    settings = load_settings()
    if not settings.mongodb_database.startswith("technologyagent_test_"):
        pytest.fail("P05 live A04 requires an isolated technologyagent_test_* database")
    application = create_app(settings)
    trace: dict = {
        "acceptance": "P05-A04",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "database": settings.mongodb_database,
        "injected_first_review": {"passed": False, "issue": "ORDER_NUMBER_IN_ANSWER"},
        "live_model_revision": True,
    }
    client = MongoClient(settings.mongodb_uri.get_secret_value())
    db = client[settings.mongodb_database]
    before = {
        "orders": db["orders"].count_documents({}),
        "order_ids": [str(value) for value in db["orders"].distinct("_id")],
        "operations": db["operations"].count_documents({"action": "order_create"}),
        "consumed_approvals": db["approvals"].count_documents({"status": "consumed"}),
        "inventory": db["inventories"].find_one({"part_id": "P001", "warehouse_id": "W01"}),
    }
    trace["database_before"] = before
    reviews = []
    original_review = workflows.semantic_review

    async def inject_first_omission_then_review_for_real(state, model, budget, ctx, *, emit=None):
        if not reviews:
            result = ReviewResult(
                passed=False,
                needs_revision=True,
                revision_count=0,
                incomplete_items=["ORDER_NUMBER_IN_ANSWER"],
                checks=[ReviewCheck(check_id="ORDER_NUMBER_IN_ANSWER", passed=False,
                                    reason="controlled test omission: include the committed order number",
                                    kind="semantic")],
            )
        else:
            result = await original_review(state, model, budget, ctx, emit=emit)
        reviews.append(result.model_dump(mode="json"))
        return result

    monkeypatch.setattr(workflows, "semantic_review", inject_first_omission_then_review_for_real)
    failure = None
    try:
        model = build_model(settings)
        assert model is not None
        with TestClient(application, base_url=f"http://127.0.0.1:{settings.api_port}",
                        client=("127.0.0.1", 50000)) as api:
            session = api.post("/api/session/local")
            assert session.status_code == 200, session.text
            service = application.state.container.order_workflows
            service._model = model
            service._model_mode = "fake"
            started = api.post("/api/order-workflows", json={
                "message": "创建P001在W01的补货订单，并在结果中给出确认单号、总数量和订单总额。",
                "request_id": "p05-a04-live-" + os.urandom(8).hex(),
                "draft": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
            })
            assert started.status_code == 200, started.text
            run = started.json()["data"]
            assert run["status"] == "waiting_input"
            service._model_mode = "live"
            resumed = api.post(f"/api/runs/{run['id']}/resume", json={
                "interrupt_id": run["pending_interrupt"]["interrupt_id"],
                "decision": "approve", "expected_version": run["pending_interrupt"]["version"],
                "payload": {}, "idempotency_key": "p05-a04-live-approve-" + run["id"],
            })
            assert resumed.status_code == 200, resumed.text
            final = api.get(f"/api/runs/{run['id']}").json()["data"]
            events = api.get(f"/api/runs/{run['id']}/events", params={"after_seq": 0}).json()["data"]
            trace.update({"run_id": run["id"], "final_run": final, "reviews": reviews, "events": events})
            assert final["status"] == "completed", final
            assert 1 <= final["revision_count"] <= 2, final
            assert len(reviews) == 2 and reviews[0]["passed"] is False and reviews[1]["passed"] is True
            assert any(event["type"] == "phase" and event["payload"].get("revision_count") == 1
                       for event in events)
            assert any(event["type"] == "run_finished" and event["payload"].get("status") == "completed"
                       for event in events)
            after = {
                "orders": db["orders"].count_documents({}),
                "operations": db["operations"].count_documents({"action": "order_create"}),
                "consumed_approvals": db["approvals"].count_documents({"status": "consumed"}),
                "inventory": db["inventories"].find_one({"part_id": "P001", "warehouse_id": "W01"}),
            }
            trace["database_after"] = after
            assert after["orders"] == before["orders"] + 1
            assert after["operations"] == before["operations"] + 1
            assert after["consumed_approvals"] == before["consumed_approvals"] + 1
            assert before["inventory"]["on_hand"] == after["inventory"]["on_hand"] == 20
            assert after["inventory"]["inbound"] == before["inventory"]["inbound"] + 55
            new_orders = [dict(item) for item in db["orders"].find({"owner_id": "local-owner"})
                          if str(item.get("_id")) not in set(before["order_ids"])]
            assert len(new_orders) == 1, new_orders
            committed = new_orders[0]
            total_quantity = sum(item.get("quantity", 0) for item in committed.get("items", []))
            order_fact = {"number": committed.get("number"), "quantity": total_quantity,
                          "total_cents": committed.get("total_cents"),
                          "items": committed.get("items", [])}
            trace["committed_order_fact"] = order_fact
            assert total_quantity == 55, order_fact
            assert committed.get("total_cents") == 66000, order_fact
            assert committed.get("number") and committed["number"] in final["summary"], {
                "order": order_fact, "answer": final["summary"]}
            verified_lines = []
            for line in committed.get("items", []):
                part = db["parts"].find_one({"_id": line.get("part_id")}) or {}
                verified_lines.append({**line, "unit": part.get("unit")})
            answer_facts_ok, answer_fact_errors = _order_answer_fact_check(
                final["summary"], [{"order": {**committed, "items": verified_lines}}]
            )
            assert answer_facts_ok, {
                "order": order_fact, "answer": final["summary"], "violations": answer_fact_errors}
    except BaseException as exc:
        failure = exc
        trace["failure"] = f"{type(exc).__name__}: {exc}"
        trace["reviews"] = reviews
        trace["database_after_failure"] = {
            "orders": db["orders"].count_documents({}),
            "operations": db["operations"].count_documents({"action": "order_create"}),
            "consumed_approvals": db["approvals"].count_documents({"status": "consumed"}),
            "inventory": db["inventories"].find_one({"part_id": "P001", "warehouse_id": "W01"}),
        }
        if "run_id" in trace:
            trace["persisted_events_after_failure"] = list(db["events"].find(
                {"run_id": trace["run_id"]}, {"_id": 0}
            ).sort("seq", 1))
    finally:
        client.close()
    trace["finished_at"] = datetime.now(timezone.utc).isoformat()
    path = Path(".runtime/live/p05-a04-attempts.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    previous.append(trace)
    path.write_text(json.dumps(previous, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    if failure is not None:
        raise failure
