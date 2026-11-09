"""Durable order writes must always be reflected in a terminal run outcome."""

import pytest
from pymongo import MongoClient

from backend.app.contracts.agent import ModelDelta
from backend.app.services.order_workflows import _render_verified_order_answer


class _OrderAnswerModel:
    async def stream(self, messages, tools, ctx):
        import json

        request = json.loads(messages[-1].content)
        yield ModelDelta(
            kind="token",
            content=_render_verified_order_answer(request["verified_orders"]["orders"]),
        )


@pytest.mark.parametrize(("failure_type", "expected_code"), [
    (RuntimeError, "POST_COMMIT_REVIEW_FAILED"),
    (TimeoutError, "POST_COMMIT_REVIEW_FAILED"),
    ("cancel", "POST_COMMIT_REVIEW_CANCELLED"),
    ("deadline", "POST_COMMIT_REVIEW_LIMIT"),
    ("limit", "POST_COMMIT_REVIEW_LIMIT"),
])
def test_review_provider_error_after_commit_finishes_run_with_committed_order_facts(
    seeded_client, monkeypatch, failure_type, expected_code
):
    from backend.app.services import order_workflows as workflows
    from backend.app.agent.budget import RunCancelled, RunDeadlineExceeded, RunLimitExceeded

    started = seeded_client.post("/api/order-workflows", json={
        "message": "创建P001在W01的补货订单",
        "request_id": "settle-review-provider-error-" + (failure_type if isinstance(failure_type, str) else failure_type.__name__),
        "draft": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
    })
    assert started.status_code == 200, started.text
    run = started.json()["data"]
    assert run["status"] == "waiting_input"
    before = seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"]

    async def fail_semantic_review(*_args, **_kwargs):
        exception = {"cancel": RunCancelled, "deadline": RunDeadlineExceeded,
                     "limit": RunLimitExceeded}.get(failure_type, failure_type)
        raise exception("provider/review failure after order commit")

    monkeypatch.setattr(workflows, "semantic_review", fail_semantic_review)
    seeded_client.app.state.container.order_workflows._model = _OrderAnswerModel()
    resumed = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": run["pending_interrupt"]["interrupt_id"],
        "decision": "approve", "expected_version": run["pending_interrupt"]["version"],
        "payload": {}, "idempotency_key": "settle-review-provider-error-approve-" + (failure_type if isinstance(failure_type, str) else failure_type.__name__),
    })

    assert resumed.status_code == 200, resumed.text
    final = seeded_client.get(f"/api/runs/{run['id']}").json()["data"]
    assert final["status"] == "failed"
    assert final["phase"] == "result"
    assert final["error_code"] == expected_code, final
    assert final["committed_facts"] is True
    assert "订单已提交" in final["summary"]
    assert "说明评审未通过" in final["summary"]
    assert "PO-" in final["summary"]
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before + 1
    settings = seeded_client.app.state.settings
    client = MongoClient(settings.mongodb_uri.get_secret_value())
    try:
        db = client[settings.mongodb_database]
        owner_id = db["runs"].find_one({"_id": run["id"]})["owner_id"]
        operations = list(db["operations"].find({
            "owner_id": owner_id, "action": "order_create", "status": "succeeded",
        }))
        assert len(operations) == 1
        order = db["orders"].find_one({"_id": operations[0]["order_id"], "owner_id": owner_id})
        assert order is not None
        assert order["number"] in final["summary"]
        assert order["items"][0]["quantity"] == 55
        assert order["total_cents"] == 66000
        assert db["approvals"].count_documents({
            "owner_id": owner_id, "status": "consumed", "order_id": order["_id"],
        }) == 1
        inventory = db["inventories"].find_one({"_id": "I001"})
        assert inventory["inbound"] == 65
        assert inventory["on_hand"] == 20
    finally:
        client.close()
    events = seeded_client.get(f"/api/runs/{run['id']}/events", params={"after_seq": 0}).json()["data"]
    assert len([item for item in events if item["type"] == "run_finished"]) == 1
    assert len([item for item in events if item["type"] == "stream_end"]) == 2
