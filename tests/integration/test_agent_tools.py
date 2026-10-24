"""P03-T03/T05: scripted model -> local read-only tools -> graph/evidence/budget."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from backend.app.agent.budget import RunBudget
from backend.app.agent.graph import GraphExecutor
from backend.app.agent.local_tools import LocalToolRegistry
from backend.app.agent.scripted_model import ScriptedModel, call_tool, token
from backend.app.contracts.agent import ExecutorInput, ModelMessage
from backend.app.contracts.common import FixedClock, RequestContext
from backend.app.repositories.catalog import CatalogRepository
from backend.app.repositories.indexes import ensure_indexes
from backend.app.repositories.inventory import InventoryRepository
from backend.app.repositories.mongo import MongoResources
from backend.app.services.seeding import seed
from tests.integration.conftest import make_settings


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, kind, payload):
        self.events.append((kind, payload))
        return None


async def _setup(db_name):
    settings = make_settings(db_name)
    mongo = await MongoResources.open(settings)
    await ensure_indexes(mongo.db)
    await seed(mongo.db, reset=True)
    clock = FixedClock(datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc))
    registry = LocalToolRegistry(CatalogRepository(mongo), InventoryRepository(mongo), clock)
    return mongo, clock, registry


def _input(message="P001 在 W01 缺多少？") -> ExecutorInput:
    return ExecutorInput(
        run_id="run_test",
        thread_id="thr_test",
        message=message,
        ctx=RequestContext(owner_id="local-owner", request_id="req", run_id="run_test"),
    )


async def _run(db_name, model, *, budget=None, message="P001 在 W01 缺多少？"):
    mongo, clock, registry = await _setup(db_name)
    try:
        async def factory(_ctx):
            return registry
        executor = GraphExecutor(model, factory, model_mode="fake")
        sink = Sink()
        outcome = await executor.execute(_input(message), sink, budget or RunBudget("run_test"))
        return outcome, sink, mongo
    finally:
        await mongo.close()


@pytest.mark.asyncio
async def test_tool_result_is_returned_to_model_and_evidence_is_collected(db_name, mongo_admin):
    try:
        def respond(messages: list[ModelMessage]):
            if messages[-1].role == "tool":
                payload = json.loads(messages[-1].content)
                assert payload["ok"] is True
                line = payload["data"]["lines"][0]
                assert line["shortage"] == 55
                return [token("P001 在 W01 的缺口是 55，推荐 S02，金额 60500 分。")]
            return [call_tool("replenishment_preview", {"part_ids": ["P001"], "warehouse_id": "W01"})]

        outcome, sink, mongo = await _run(db_name, ScriptedModel(responder=respond))
        assert outcome.status == "completed"
        assert "55" in outcome.summary
        assert [kind for kind, _ in sink.events].count("tool_started") == 1
        finished = [payload for kind, payload in sink.events if kind == "tool_finished"]
        assert finished[0]["status"] == "success"
        assert finished[0]["source"] == "local_seed"
        # tool result persisted 的 evidence 在最终回答前参与硬校验
    finally:
        mongo_admin.drop_database(db_name)


@pytest.mark.asyncio
async def test_unknown_tool_and_invalid_args_are_reported_not_executed(db_name, mongo_admin):
    try:
        def respond(messages: list[ModelMessage]):
            if messages[-1].role == "tool":
                return [token("工具调用失败，未完成查询。")]
            return [call_tool("order_create", {"part_id": "P001"}), call_tool("inventory_get", {})]

        outcome, sink, mongo = await _run(db_name, ScriptedModel(responder=respond))
        assert outcome.status == "completed"
        finished = [payload for kind, payload in sink.events if kind == "tool_finished"]
        assert finished and all(item["status"] == "error" for item in finished)
        assert any("UNKNOWN_TOOL" in (item["error"] or "") for item in finished)
        assert any("INVALID_ARGUMENTS" in (item["error"] or "") for item in finished)
    finally:
        mongo_admin.drop_database(db_name)


@pytest.mark.asyncio
async def test_order_claim_is_rejected_even_if_model_says_it_ordered(db_name, mongo_admin):
    try:
        outcome, _sink, mongo = await _run(
            db_name,
            ScriptedModel(steps=[[token("已下单，订单已创建。")]]),
            message="直接帮我下单",
        )
        assert outcome.status == "failed"
        assert outcome.error_code == "UNSUPPORTED_OPERATION"
    finally:
        mongo_admin.drop_database(db_name)


@pytest.mark.asyncio
async def test_model_call_limit_stops_tool_loop(db_name, mongo_admin):
    try:
        def respond(messages: list[ModelMessage]):
            return [call_tool("inventory_page", {"warehouse_id": "W01", "page_size": 1})]

        outcome, _sink, mongo = await _run(
            db_name,
            ScriptedModel(responder=respond),
            budget=RunBudget("run_test", max_model_calls=1),
        )
        assert outcome.status == "failed"
        assert outcome.error_code == "LIMIT_EXCEEDED"
    finally:
        mongo_admin.drop_database(db_name)
