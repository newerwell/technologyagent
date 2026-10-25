"""Order review may revise prose, but must never replay the committed mutation."""

import json

from pymongo import MongoClient

from backend.app.contracts.agent import ModelDelta


class _ReviewThenPassModel:
    def __init__(self):
        self.review_calls = 0
        self.revision_calls = 0
        self.review_requests = []

    async def stream(self, messages, tools, ctx):
        if "语义完整性检查器" in messages[0].content:
            self.review_calls += 1
            request = json.loads(messages[-1].content)
            self.review_requests.append(request)
            answer = ('{"passed":false,"issues":["请补充已确认订单号"]}'
                      if self.review_calls == 1 else '{"passed":true,"issues":[]}')
            yield ModelDelta(kind="token", content=answer)
            return
        self.revision_calls += 1
        payload = json.loads(messages[-1].content)
        number = payload["verified_orders"]["orders"][0]["order"]["number"]
        yield ModelDelta(kind="token", content=f"订单已提交，已确认单号{number}。")


class _AlwaysFailReviewModel(_ReviewThenPassModel):
    async def stream(self, messages, tools, ctx):
        if "语义完整性检查器" in messages[0].content:
            self.review_calls += 1
            self.review_requests.append(json.loads(messages[-1].content))
            yield ModelDelta(kind="token", content='{"passed":false,"issues":["说明仍缺订单号"]}')
            return
        self.revision_calls += 1
        yield ModelDelta(kind="token", content="订单已提交，说明仍不完整。")


class _WrongThenCorrectFactsModel(_ReviewThenPassModel):
    def __init__(self):
        super().__init__()
        self.revision_texts = []

    async def stream(self, messages, tools, ctx):
        if "语义完整性检查器" in messages[0].content:
            self.review_calls += 1
            request = json.loads(messages[-1].content)
            self.review_requests.append(request)
            answer = '{"passed":false,"issues":["补充订单结果"]}' if self.review_calls == 1 else '{"passed":true,"issues":[]}'
            yield ModelDelta(kind="token", content=answer)
            return
        self.revision_calls += 1
        payload = json.loads(messages[-1].content)
        order = payload["verified_orders"]["orders"][0]["order"]
        number = order["number"]
        answer = (f"订单已提交，数量999件，总额9999分，单号{number}。" if self.revision_calls == 1 else
                  f"订单已提交，数量{order['items'][0]['quantity']}件，总额{order['total_cents']}分，单号{number}。")
        self.revision_texts.append(answer)
        yield ModelDelta(kind="token", content=answer)


def test_order_a04_revises_missing_order_number_without_replaying_commit(seeded_client):
    message = "创建P001在W01的补货订单，并在结果中给出确认单号。"
    started = seeded_client.post("/api/order-workflows", json={
        "message": message,
        "request_id": "order-review-revision-a04",
        "draft": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
    })
    assert started.status_code == 200, started.text
    run = started.json()["data"]
    assert run["status"] == "waiting_input"
    before = seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"]
    model = _ReviewThenPassModel()
    seeded_client.app.state.container.order_workflows._model = model

    resumed = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": run["pending_interrupt"]["interrupt_id"],
        "decision": "approve", "expected_version": run["pending_interrupt"]["version"],
        "payload": {}, "idempotency_key": "order-review-revision-a04-approve",
    })

    assert resumed.status_code == 200, resumed.text
    final = seeded_client.get(f"/api/runs/{run['id']}").json()["data"]
    assert final["status"] == "completed"
    assert final["revision_count"] == 1
    assert final["review"]["passed"] is True
    assert model.review_calls == 2
    assert model.revision_calls == 1
    assert all(item["request"] == message for item in model.review_requests)
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before + 1

    settings = seeded_client.app.state.settings
    client = MongoClient(settings.mongodb_uri.get_secret_value())
    try:
        db = client[settings.mongodb_database]
        assert db["operations"].count_documents({"action": "order_create"}) == 1
        assert db["approvals"].count_documents({"status": "consumed"}) == 1
    finally:
        client.close()


def test_order_review_stops_after_three_checks_and_two_prose_revisions(seeded_client):
    message = "创建P001在W01的补货订单，并在结果中给出确认单号。"
    started = seeded_client.post("/api/order-workflows", json={
        "message": message, "request_id": "order-review-two-revisions-fail",
        "draft": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
    })
    run = started.json()["data"]
    before = seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"]
    model = _AlwaysFailReviewModel()
    seeded_client.app.state.container.order_workflows._model = model
    resumed = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": run["pending_interrupt"]["interrupt_id"], "decision": "approve",
        "expected_version": run["pending_interrupt"]["version"], "payload": {},
        "idempotency_key": "order-review-two-revisions-fail-approve",
    })
    assert resumed.status_code == 200, resumed.text
    final = seeded_client.get(f"/api/runs/{run['id']}").json()["data"]
    assert final["status"] == "failed"
    assert final["committed_facts"] is True
    assert final["revision_count"] == 2
    assert model.review_calls == 3
    assert model.revision_calls == 2
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before + 1
    settings = seeded_client.app.state.settings
    client = MongoClient(settings.mongodb_uri.get_secret_value())
    try:
        db = client[settings.mongodb_database]
        assert db["operations"].count_documents({"action": "order_create"}) == 1
        assert db["approvals"].count_documents({"status": "consumed"}) == 1
        assert db["inventories"].find_one({"_id": "I001"})["inbound"] == 65
    finally:
        client.close()


def test_order_fact_gate_rejects_wrong_revised_quantity_and_amount(seeded_client):
    started = seeded_client.post("/api/order-workflows", json={
        "message": "创建P001在W01的补货订单，并在结果中给出数量、金额和单号。",
        "request_id": "order-review-wrong-facts",
        "draft": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
    })
    assert started.status_code == 200, started.text
    run = started.json()["data"]
    before = seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"]
    model = _WrongThenCorrectFactsModel()
    seeded_client.app.state.container.order_workflows._model = model
    resumed = seeded_client.post(f"/api/runs/{run['id']}/resume", json={
        "interrupt_id": run["pending_interrupt"]["interrupt_id"], "decision": "approve",
        "expected_version": run["pending_interrupt"]["version"], "payload": {},
        "idempotency_key": "order-review-wrong-facts-approve",
    })
    assert resumed.status_code == 200, resumed.text
    final = seeded_client.get(f"/api/runs/{run['id']}").json()["data"]
    assert final["status"] == "completed"
    assert final["revision_count"] == 2
    assert "999件" in model.revision_texts[0] and "9999分" in model.revision_texts[0]
    assert "999件" not in final["summary"] and "9999分" not in final["summary"]
    events = seeded_client.get(f"/api/runs/{run['id']}/events", params={"after_seq": 0}).json()["data"]
    assert any(check.get("check_id") == "ORDER_FACTS_MATCH" and not check.get("passed")
               for event in events if event["type"] == "review"
               for check in event["payload"].get("details", []))
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before + 1
