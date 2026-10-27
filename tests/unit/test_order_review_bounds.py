import asyncio
import json
import time
from pathlib import Path

import pytest

from backend.app.agent.budget import RunBudget, RunCancelled
from backend.app.contracts.agent import ModelDelta
from backend.app.contracts.common import RequestContext
from backend.app.contracts.workflow import ReviewResult
from backend.app.services.order_workflows import OrderWorkflowService, _order_answer_fact_check
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
    assert _order_answer_fact_check("订单数量55套，总额66000分。", orders)[0]
    valid, violations = _order_answer_fact_check("订单数量999件，总额9999分。", orders)
    assert not valid
    assert len(violations) == 2


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
        assert _order_answer_fact_check(answer, orders)[0]
    for answer in fixture["expected_claims"]["rejected"]:
        assert not _order_answer_fact_check(answer, orders)[0]


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
