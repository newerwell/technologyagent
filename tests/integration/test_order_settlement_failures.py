"""Durable order writes must always be reflected in a terminal run outcome."""

import pytest


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
    seeded_client.app.state.container.order_workflows._model = object()
    resumed = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": run["pending_interrupt"]["interrupt_id"],
        "decision": "approve", "expected_version": run["pending_interrupt"]["version"],
        "payload": {}, "idempotency_key": "settle-review-provider-error-approve-" + (failure_type if isinstance(failure_type, str) else failure_type.__name__),
    })

    assert resumed.status_code == 200, resumed.text
    final = seeded_client.get(f"/api/runs/{run['id']}").json()["data"]
    assert final["status"] == "failed"
    assert final["phase"] == "result"
    assert final["error_code"] == expected_code
    assert final["committed_facts"] is True
    assert "已提交" in final["summary"]
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before + 1
    events = seeded_client.get(f"/api/runs/{run['id']}/events", params={"after_seq": 0}).json()["data"]
    assert len([item for item in events if item["type"] == "run_finished"]) == 1
    assert len([item for item in events if item["type"] == "stream_end"]) == 2
