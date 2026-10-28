"""Order review may revise prose, but must never replay the committed mutation."""

import json

from pymongo import MongoClient

from backend.app.contracts.agent import ModelDelta


class _ReviewThenPassModel:
    def __init__(self):
        self.review_calls = 0
        self.revision_calls = 0
        self.review_requests = []

    @staticmethod
    def _complete_answer(order):
        facts = order.get("verification_facts", {})
        saved_items = facts.get("items", [])
        lines = []
        for line in order.get("items", []):
            saved = next((item for item in saved_items if item.get("part_id") == line.get("part_id")), {})
            unit = saved.get("unit")
            quantity = f"{line['quantity']}{unit}" if unit else f"{line['quantity']}（单位未知）"
            lines.append(f"{line['part_id']}数量{quantity}")
        text = f"订单已提交，{'；'.join(lines)}，总额{order['total_cents']}分，单号{order['number']}。"
        constraints = facts.get("request_constraints", {})
        if constraints.get("max_lead_days") is not None:
            text += f"用户要求{constraints['max_lead_days']}天内到货；"
            text += "；".join(
                f"{item.get('part_id')}批准报价交期{item['lead_days']}天"
                for item in saved_items if isinstance(item.get("lead_days"), int)
            )
            text += "。以上为报价交期，不代表已经到货。"
        return text

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
        order = payload["verified_orders"]["orders"][0]["order"]
        yield ModelDelta(kind="token", content=self._complete_answer(order))


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
        saved = order.get("verification_facts", {})
        fact_item = (saved.get("items") or [{}])[0]
        unit = fact_item.get("unit", "")
        constraints = saved.get("request_constraints", {})
        coverage = (f"用户要求{constraints['max_lead_days']}天内到货，批准报价交期{fact_item['lead_days']}天。"
                    if constraints.get("max_lead_days") is not None else "")
        answer = (f"订单已提交，数量999{unit}，总额9999分，单号{number}。{coverage}" if self.revision_calls == 1 else
                  f"订单已提交，数量{order['items'][0]['quantity']}{unit}，总额{order['total_cents']}分，单号{number}。{coverage}")
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
    assert "999" in model.revision_texts[0] and "9999分" in model.revision_texts[0]
    assert "999" not in final["summary"] and "9999分" not in final["summary"]
    events = seeded_client.get(f"/api/runs/{run['id']}/events", params={"after_seq": 0}).json()["data"]
    assert any(check.get("check_id") == "ORDER_FACTS_MATCH" and not check.get("passed")
               for event in events if event["type"] == "review"
               for check in event["payload"].get("details", []))
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == before + 1
    settings = seeded_client.app.state.settings
    client = MongoClient(settings.mongodb_uri.get_secret_value())
    try:
        db = client[settings.mongodb_database]
        owner_id = db["runs"].find_one({"_id": run["id"]})["owner_id"]
        operations = list(db["operations"].find({"action": "order_create", "owner_id": owner_id}))
        assert len(operations) == 1
        persisted = db["orders"].find_one({"_id": operations[0]["order_id"], "owner_id": owner_id})
        assert persisted is not None
        assert len(persisted["items"]) == 1
        item = persisted["items"][0]
        assert item["quantity"] == 55
        assert item["line_total_cents"] == 66000
        assert persisted["total_cents"] == 66000
        assert persisted["number"] in final["summary"]
        assert "55套" in final["summary"]
        assert "660" in final["summary"]
        facts = persisted["verification_facts"]
        assert facts["request_constraints"] == {"max_lead_days": 7}
        assert facts["items"] == [{
            "part_id": "P001", "warehouse_id": "W01", "quantity": 55,
            "quote_id": "Q01", "supplier_id": "S01", "lead_days": 5,
            "quote_observed_at": facts["submitted_at"], "unit": "套",
        }]
        inventory = db["inventories"].find_one({"_id": "I001"})
        assert inventory["inbound"] == 65
        assert inventory["on_hand"] == 20
    finally:
        client.close()
