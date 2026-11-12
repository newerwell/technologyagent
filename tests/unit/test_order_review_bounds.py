import asyncio
import json
import time
from types import SimpleNamespace
from pathlib import Path

import pytest

from backend.app.agent.budget import RunBudget, RunCancelled
from backend.app.contracts.agent import ModelDelta
from backend.app.contracts.common import RequestContext
from backend.app.contracts.workflow import ReviewResult
from backend.app.integrations.model import ModelProviderError
from backend.app.services.order_workflows import (
    OrderWorkflowService,
    _order_answer_fact_check,
    _receipt_claims_for_order,
    _render_verified_order_answer,
)
from unittest.mock import AsyncMock


class _SilentModel:
    async def stream(self, messages, tools, ctx):
        await asyncio.Event().wait()
        if False:
            yield ModelDelta(kind="token", content="")


def test_order_answer_numeric_facts_must_match_persisted_commit():
    orders = [{"order": {"_id": "ord-1", "number": "PO-1", "total_cents": 66000,
                          "items": [{"part_id": "P001", "unit": "套", "quantity": 55,
                                     "unit_price_cents": 1200, "line_total_cents": 66000}]}}]
    assert _order_answer_fact_check("PO-1订单数量55套，总额66000分。", orders)[0]
    valid, violations = _order_answer_fact_check("PO-1订单数量999件，总额9999分。", orders)
    assert not valid
    assert any("numeric claim" in item for item in violations)


def test_order_answer_requires_quantity_and_total_coverage_after_commit():
    orders = [{"order": {"_id": "ord-1", "number": "PO-1", "total_cents": 66000,
                          "items": [{"part_id": "P001", "unit": "套", "quantity": 55,
                                     "unit_price_cents": 1200, "line_total_cents": 66000}]}}]

    valid, violations = _order_answer_fact_check("订单已提交，单号PO-1。", orders)

    assert not valid
    assert any("quantity" in item or "数量" in item for item in violations)
    assert any("total" in item or "总额" in item for item in violations)


def test_order_answer_covers_saved_delivery_constraint_and_quote_lead_without_claiming_receipt():
    orders = [{"order": {
        "_id": "ord-1", "number": "PO-1", "total_cents": 66000,
        "items": [{"part_id": "P001", "unit": "套", "quantity": 55,
                   "unit_price_cents": 1200, "line_total_cents": 66000}],
        "verification_facts": {
            "request_constraints": {"max_lead_days": 7},
            "items": [{"part_id": "P001", "lead_days": 5}],
        },
    }}]

    missing_delivery, _ = _order_answer_fact_check("PO-1订单数量55套，总额66000分。", orders)
    matching, violations = _order_answer_fact_check(
        "PO-1订单数量55套，总额66000分。用户要求7天内到货，批准报价交期5天，不代表已经到货。", orders
    )
    false_receipt, receipt_violations = _order_answer_fact_check(
        "PO-1订单数量55套，总额66000分，已经到货。用户要求7天内到货，批准报价交期5天。", orders
    )

    assert not missing_delivery
    assert matching, violations
    assert not false_receipt
    assert any("receipt" in item for item in receipt_violations)


def test_order_answer_accepts_explicit_unit_parenthesis_and_saved_delivery_wording():
    orders = [{"order": {
        "_id": "ord-1", "number": "PO-1", "total_cents": 66000,
        "items": [{"part_id": "P001", "unit": "套", "quantity": 55,
                   "unit_price_cents": 1200, "line_total_cents": 66000}],
        "verification_facts": {
            "request_constraints": {"max_lead_days": 7},
            "items": [{"part_id": "P001", "lead_days": 5}],
        },
    }}]
    answer = (
        "订单PO-1已提交，明细为P001数量55（单位：套），订单总额为66,000分。"
        "用户要求的最晚交期为7天内；该订单对应的已批准报价交期为5天。报价交期5天不代表已到货。"
    )

    valid, violations = _order_answer_fact_check(answer, orders)

    assert valid, violations


def test_order_answer_rejects_completed_receipt_without_receipt_fact():
    orders = [{"order": {"_id": "ord-1", "number": "PO-1", "status": "submitted",
                          "total_cents": 66000,
                          "items": [{"part_id": "P001", "quantity": 55, "unit": "套"}]}}]

    valid, violations = _order_answer_fact_check(
        "PO-1订单数量55套、总额66000分，订单已完成收货。", orders
    )

    assert not valid
    assert any("receipt" in item for item in violations)


def test_fake_order_answer_is_rendered_only_from_verified_persisted_facts():
    orders = [{"order": {
        "_id": "ord-1", "number": "PO-1", "status": "submitted", "total_cents": 66000,
        "items": [{"part_id": "P001", "quantity": 55}],
        "verification_facts": {
            "request_constraints": {"max_lead_days": 7},
            "items": [{"part_id": "P001", "warehouse_id": "W01", "quantity": 55,
                       "unit": "套", "quote_id": "Q01", "supplier_id": "S01",
                       "lead_days": 5, "quote_observed_at": "2026-10-23T00:00:00Z"}],
        },
    }}]

    answer = _render_verified_order_answer(orders)
    valid, violations = _order_answer_fact_check(answer, orders)
    assert valid, violations
    assert "PO-1" in answer
    assert "55套" in answer
    assert "66000分" in answer
    assert "用户要求7天内到货" in answer
    assert "批准报价交期5天" in answer
    assert "不代表已经到货" in answer


def test_fake_order_answer_keeps_missing_historical_facts_unknown():
    orders = [{"order": {
        "_id": "old-order", "number": "PO-OLD", "status": "submitted", "total_cents": 100,
        "items": [{"part_id": "P001", "quantity": 1}],
    }}]

    answer = _render_verified_order_answer(orders)

    assert "单位未知" in answer
    assert "没有保存用户交期要求" in answer
    assert "报价交期未知" in answer


def test_fake_order_settlement_finishes_with_complete_verified_answer_without_model():
    class Collection:
        def __init__(self, documents):
            self.documents = documents

        async def find_one(self, query):
            for document in self.documents:
                if all(document.get(key) == value for key, value in query.items()):
                    return document
            return None

    class Database:
        def __init__(self):
            self.collections = {
                "runs": Collection([{"_id": "run-1", "owner_id": "owner-1", "message": "补货 P001"}]),
                "operations": Collection([{"_id": "op-1", "owner_id": "owner-1", "action": "order_create",
                                            "status": "succeeded", "order_id": "order-1"}]),
                "orders": Collection([{"_id": "order-1", "owner_id": "owner-1", "operation_id": "op-1",
                                        "number": "PO-1", "status": "submitted", "warehouse_id": "W01",
                                        "supplier_id": "S01", "total_cents": 66000,
                                        "items": [{"part_id": "P001", "quantity": 55,
                                                   "unit_price_cents": 1200, "line_total_cents": 66000}],
                                        "verification_facts": {
                                            "request_constraints": {"max_lead_days": 7},
                                            "items": [{"part_id": "P001", "warehouse_id": "W01",
                                                       "quantity": 55, "unit": "套", "quote_id": "Q01",
                                                       "supplier_id": "S01", "lead_days": 5,
                                                       "quote_observed_at": "2026-10-23T00:00:00Z"}],
                                        }}]),
                "approvals": Collection([{"_id": "approval-1", "owner_id": "owner-1", "status": "consumed",
                                           "order_id": "order-1"}]),
            }

        def __getitem__(self, name):
            return self.collections[name]

    class Runs:
        class Clock:
            @staticmethod
            def now():
                from datetime import datetime, timezone
                return datetime(2026, 10, 23, tzinfo=timezone.utc)

        _clock = Clock()

        def __init__(self):
            self.finished = None

        async def append_event(self, *args, **kwargs):
            return None

        async def charge_model(self, *args, **kwargs):
            raise AssertionError("fake settlement must not call a model")

        async def cancel_requested(self, *args, **kwargs):
            return False

        async def finish(self, run_id, outcome, ctx):
            self.finished = outcome
            return outcome

    async def scenario():
        service = object.__new__(OrderWorkflowService)
        service._mongo = type("Mongo", (), {"db": Database()})()
        service._runs = Runs()
        service._model = None
        service._catalog = None
        ctx = RequestContext(owner_id="owner-1", request_id="req-1", run_id="run-1")
        outcome = await service._settle({
            "order_results": [{"order": {"id": "order-1"}, "operation_id": "op-1"}],
        }, "run-1", ctx)
        return outcome, service._runs.finished

    outcome, finished = asyncio.run(scenario())

    assert outcome.status == "completed"
    assert finished.summary == outcome.summary
    assert all(text in outcome.summary for text in (
        "PO-1", "55套", "66000分", "用户要求7天内到货", "批准报价交期5天", "不代表已经到货",
    ))


def test_order_answer_accepts_grouped_cents_only_when_quantity_and_order_total_match():
    orders = [{"order": {"_id": "ord-1", "number": "PO-1", "total_cents": 66000,
                          "items": [{"part_id": "P001", "unit": "片", "quantity": 55,
                                     "unit_price_cents": 1200, "line_total_cents": 66000}]}}]

    valid, violations = _order_answer_fact_check(
        "PO-1\u8ba2\u5355\u6570\u91cf55\u7247\uff0c\u8ba2\u5355\u603b\u989d66,000\u5206\u3002", orders
    )
    assert valid, violations
    wrong_amount, _ = _order_answer_fact_check(
        "PO-1\u8ba2\u5355\u6570\u91cf55\u7247\uff0c\u8ba2\u5355\u603b\u989d66,001\u5206\u3002", orders
    )
    wrong_unit, _ = _order_answer_fact_check(
        "PO-1\u8ba2\u5355\u6570\u91cf55\u4ef6\uff0c\u8ba2\u5355\u603b\u989d66,000\u5206\u3002", orders
    )
    wrong_quantity, _ = _order_answer_fact_check(
        "PO-1\u8ba2\u5355\u6570\u91cf56\u7247\uff0c\u8ba2\u5355\u603b\u989d66,000\u5206\u3002", orders
    )
    assert not wrong_amount
    assert not wrong_unit
    assert not wrong_quantity


def test_order_answer_money_is_bound_to_price_or_order_total_field():
    fixture = json.loads(Path("tests/fixtures/p06_fix2/order_facts.json").read_text(encoding="utf-8"))
    orders = fixture["verified_orders"]

    for answer in fixture["expected_claims"]["accepted"]:
        matching = [item for item in orders if item["order"].get("number", "").upper() in answer.upper()]
        assert len(matching) == 1
        assert _order_answer_fact_check(answer, matching)[0]
    for answer in fixture["expected_claims"]["rejected"]:
        matching = [item for item in orders if item["order"].get("number", "").upper() in answer.upper()]
        assert not _order_answer_fact_check(answer, matching or orders)[0]


def test_order_answer_cannot_borrow_amount_from_another_order():
    orders = [
        {"order": {"_id": "ord-1", "number": "PO-1", "total_cents": 66000,
                    "items": [{"part_id": "P001", "unit": "套", "quantity": 55,
                               "unit_price_cents": 1200, "line_total_cents": 66000}]}},
        {"order": {"_id": "ord-2", "number": "PO-2", "total_cents": 60500,
                    "items": [{"part_id": "P002", "unit": "个", "quantity": 55,
                               "unit_price_cents": 1100, "line_total_cents": 60500}]}},
    ]

    valid, violations = _order_answer_fact_check("PO-2订单总额660元。", orders)

    assert not valid
    assert violations


def test_silent_order_revision_observes_cancel_and_closes_stream():
    async def scenario():
        cancelled_at = time.monotonic() + 0.05

        async def cancel_check():
            return time.monotonic() >= cancelled_at

        service = object.__new__(OrderWorkflowService)
        service._model = _SilentModel()
        budget = RunBudget("silent-order", max_active_seconds=2, cancel_check=cancel_check)
        try:
            await service._revise_order_answer(
                "request", "old answer", [], ReviewResult(passed=False), budget,
                RequestContext(owner_id="owner", request_id="req", run_id="silent-order"),
            )
        except RunCancelled:
            return
        raise AssertionError("silent model stream ignored cancellation")

    asyncio.run(asyncio.wait_for(scenario(), timeout=1))


def test_order_answer_revision_uses_collector_retry_and_counts_each_attempt():
    class InterruptedOnce:
        def __init__(self):
            self.calls = 0

        async def stream(self, _messages, _tools, _ctx):
            self.calls += 1
            if self.calls == 1:
                raise ModelProviderError("connection reset", code="MODEL_UNAVAILABLE")
            yield ModelDelta(kind="token", content="PO-1，55套，660元。")

    async def scenario():
        model = InterruptedOnce()
        service = object.__new__(OrderWorkflowService)
        service._model = model
        events = []

        async def append_event(_run_id, kind, payload, _ctx):
            events.append((kind, payload))

        service._runs = SimpleNamespace(append_event=append_event)
        charges = []

        async def charge():
            charges.append(1)
            return True

        answer = await service._revise_order_answer(
            "request", "old answer", [], ReviewResult(passed=False),
            RunBudget("order-revision", model_counter=charge),
            RequestContext("owner", "request", run_id="order-revision"),
        )
        assert answer == "PO-1，55套，660元。"
        assert model.calls == len(charges) == 2
        started = next(payload for kind, payload in events if kind == "model_started")
        assert started["prompt_template_id"] == "ta-order-answer-revision-1"

    asyncio.run(scenario())


def test_recovery_records_persisted_resume_idempotency_result():
    async def scenario():
        service = object.__new__(OrderWorkflowService)
        result = object()
        service._runs = type("Runs", (), {"record_decision_result": AsyncMock()})()
        graph = type("Graph", (), {"ainvoke": AsyncMock(return_value={})})()
        service._graph = lambda: graph
        service._settle_protected = AsyncMock(return_value=result)
        await service._recover_one({
            "_id": "run-1", "owner_id": "owner", "thread_id": "thread",
            "resume_request": {"decision": "edit", "idempotency_key": "edit-key", "payload": {}},
        })
        service._runs.record_decision_result.assert_awaited_once()
        assert service._runs.record_decision_result.await_args.args[1] == "edit-key"
        assert service._runs.record_decision_result.await_args.args[2] is result

    asyncio.run(scenario())


def test_fake_settlement_validates_multiple_alphanumeric_order_numbers_independently():
    orders = []
    for index, (number, part_id, quantity, total, unit) in enumerate((
        ("PO-41A9C1F5C3", "P001", 55, 66000, "\u5957"),
        ("PO-29893199EA", "P002", 20, 24000, "\u4e2a"),
    )):
        order = {
            "_id": f"order-{index}", "number": number, "status": "submitted",
            "warehouse_id": "W01", "supplier_id": f"S0{index + 1}", "total_cents": total,
            "items": [{"part_id": part_id, "quantity": quantity, "unit": unit,
                       "unit_price_cents": total // quantity, "line_total_cents": total}],
            "verification_facts": {"request_constraints": {}, "items": [{
                "part_id": part_id, "warehouse_id": "W01", "supplier_id": f"S0{index + 1}",
                "quantity": quantity, "unit": unit, "lead_days": 5,
            }]},
        }
        orders.append({"order": order, "operation": {"status": "succeeded"},
                       "approval": {"status": "consumed"}})

    answer = _render_verified_order_answer(orders)
    valid, violations = _order_answer_fact_check(answer, orders)
    assert valid, violations


def _receipt_order(number="PO-1", *, status="submitted", quantity=55, total=66000, part_id="P001"):
    return {"order": {
        "_id": "order-" + number, "number": number, "status": status, "total_cents": total,
        "items": [{"part_id": part_id, "unit": "套", "quantity": quantity,
                   "unit_price_cents": total // quantity, "line_total_cents": total}],
        "verification_facts": {"request_constraints": {"max_lead_days": 7}, "items": [
            {"part_id": part_id, "unit": "套", "lead_days": 5},
        ]},
    }}


@pytest.mark.parametrize("claim", [
    "交期不代表已经到货。", "交期不表示已经到货。", "报价交期不意味着已经收货。",
    "报价交期并非意味着已经到货。",
])
def test_negative_receipt_implication_is_allowed(claim):
    orders = [_receipt_order()]
    answer = f"PO-1数量55套，总额66000分。用户要求7天内到货，批准报价交期5天。{claim}"

    valid, violations = _order_answer_fact_check(answer, orders)

    assert valid, violations


@pytest.mark.parametrize("claim", [
    "已经到货。", "订单已完成收货。", "尚未收货。已到货。", "尚未收货，但已到货。", "未确认。已入库。",
])
def test_asserted_receipt_without_saved_receipt_fails(claim):
    orders = [_receipt_order()]
    answer = f"PO-1数量55套，总额66000分。用户要求7天内到货，批准报价交期5天。{claim}"

    valid, violations = _order_answer_fact_check(answer, orders)

    assert not valid
    assert any("receipt" in item for item in violations)


def test_delivery_promise_is_not_actual_receipt():
    orders = [_receipt_order()]
    answer = "PO-1数量55套，总额66000分。用户要求7天内到货；批准时报价交期5天；尚未实际收货。"

    valid, violations = _order_answer_fact_check(answer, orders)

    assert valid, violations


def test_receipt_claim_is_scoped_to_its_order():
    orders = [
        _receipt_order("PO-41A9C1F5C3", status="received"),
        _receipt_order("PO-29893199EA", status="submitted", quantity=20, total=24000, part_id="P002"),
    ]
    for entry in orders:
        entry["order"].pop("verification_facts")
    answer = (
        "PO-41A9C1F5C3 P001数量55套，总额66000分，已经到货。"
        "PO-29893199EA P002数量20套，总额24000分，尚未收货。"
    )

    assert _receipt_claims_for_order(answer, "PO-41A9C1F5C3", orders)
    assert not _receipt_claims_for_order(answer, "PO-29893199EA", orders)

def test_committed_answer_allows_separate_quantity_and_unit_label():
    orders = [{
        "operation_id": "operation-1",
        "operation": {"_id": "operation-1", "status": "succeeded"},
        "approval": {"_id": "approval-1", "status": "consumed"},
        "order": {
            "_id": "persisted-1", "number": "PO-5ED6C6DE5D", "status": "submitted",
            "warehouse_id": "W01", "supplier_id": "S01", "total_cents": 66000,
            "items": [{"part_id": "P001", "unit": "套", "quantity": 55,
                       "unit_price_cents": 1200, "line_total_cents": 66000}],
            "verification_facts": {
                "request_constraints": {"max_lead_days": 7},
                "items": [{"part_id": "P001", "warehouse_id": "W01", "supplier_id": "S01",
                           "unit": "套", "quote_id": "Q01", "lead_days": 5}],
            },
        },
    }]
    answer = (
        "订单 PO-5ED6C6DE5D 已提交：P001，数量 55，单位 套；订单总额 66000 分（¥660.00）。"
        "用户要求的最晚交期为 7 天内到货；已批准报价交期为 5 天，该 5 天为报价交期，不代表已到货。"
    )

    valid, violations = _order_answer_fact_check(answer, orders)

    assert valid, violations
    assert not _order_answer_fact_check(answer.replace("数量 55", "数量 56"), orders)[0]
    assert not _order_answer_fact_check(answer.replace("单位 套", "单位 件"), orders)[0]
    assert not _order_answer_fact_check(answer.replace("66000 分", "66100 分"), orders)[0]
