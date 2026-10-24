"""P03-T03/T05: scripted model -> local read-only tools -> graph/evidence/budget."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from backend.app.agent.budget import RunBudget
from backend.app.agent.budget import RunDeadlineExceeded
from backend.app.agent.graph import GraphExecutor
from backend.app.agent.local_tools import LocalToolRegistry
from backend.app.agent.scripted_model import ScriptedModel, call_tool, token
from backend.app.contracts.agent import ExecutorInput, ModelDelta, ModelMessage, ModelToolCall
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
        assert any(fact.get("call_id") and fact.get("field") == "shortage" and fact.get("value") == 55 for fact in outcome.evidence)
        assert [kind for kind, _ in sink.events].count("tool_started") == 1
        finished = [payload for kind, payload in sink.events if kind == "tool_finished"]
        assert finished[0]["status"] == "success"
        assert finished[0]["source"] == "local_seed"
        # tool result persisted 的 evidence 在最终回答前参与硬校验
    finally:
        mongo_admin.drop_database(db_name)


@pytest.mark.asyncio
async def test_semantic_review_receives_original_user_request_after_langgraph_state_filtering(db_name, mongo_admin):
    question = "P001 在 W01 缺多少？请只回答缺口。"
    model = ScriptedModel(steps=[
        [call_tool("replenishment_preview", {"part_ids": ["P001"], "warehouse_id": "W01"})],
        [token("P001 在 W01 缺口55件。")],
    ])
    semantic_payloads = []

    async def capture(messages, tools, ctx):
        if messages and "语义完整性检查器" in messages[0].content:
            semantic_payloads.append(json.loads(messages[-1].content))
            yield token('{"passed":true,"issues":[]}')
        else:
            async for item in model.stream(messages, tools, ctx):
                yield item

    class CapturingModel:
        stream = staticmethod(capture)

    try:
        outcome, _, mongo = await _run(db_name, CapturingModel(), message=question)
        assert outcome.status == "completed"
        assert semantic_payloads
        assert semantic_payloads[0]["request"] == question
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
        assert outcome.status == "failed"
        assert outcome.error_code == "REVIEW_FAILED"
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
        assert not [payload for kind, payload in _sink.events if kind == "token"]
    finally:
        mongo_admin.drop_database(db_name)


@pytest.mark.asyncio
async def test_fragmented_and_interleaved_tool_arguments_execute_once_with_complete_arguments(db_name, mongo_admin):
    class FragmentModel:
        def __init__(self):
            self.calls = 0
        async def stream(self, messages, tools, ctx):
            if messages and "语义完整性检查器" in messages[0].content:
                yield token('{"passed":true,"issues":[]}')
                return
            self.calls += 1
            if self.calls == 1:
                for index, call_id, name, arguments in [
                    (0, "c0", "inventory_get", '{"inventory_id":'),
                    (1, "c1", "inventory_get", '{"inventory_id":'),
                    (0, "", "", '"I001"}'),
                    (1, "", "", '"I002"}'),
                ]:
                    yield ModelDelta(kind="tool_call", tool_call=ModelToolCall(
                        id=call_id, name=name, arguments=arguments, index=index,
                    ))
            else:
                yield ModelDelta(kind="token", content="已读取两条库存记录。")

    try:
        model = FragmentModel()
        outcome, sink, mongo = await _run(db_name, model)
        starts = [payload for kind, payload in sink.events if kind == "tool_started"]
        assert outcome.status == "completed"
        finished = [payload for kind, payload in sink.events if kind == "tool_finished"]
        assert [item["args_summary"] for item in starts] == [
            {"inventory_id": "I001"}, {"inventory_id": "I002"}
        ]
        assert len(finished) == 2 and all(item["status"] == "success" for item in finished)
    finally:
        mongo_admin.drop_database(db_name)


@pytest.mark.asyncio
async def test_invalid_final_tool_json_is_reported_and_never_invoked(db_name, mongo_admin):
    class BadJsonModel:
        async def stream(self, messages, tools, ctx):
            if any(message.role == "tool" for message in messages):
                yield token("查询未完成。")
                return
            yield ModelDelta(kind="tool_call", tool_call=ModelToolCall(
                id="bad-json", name="inventory_get", arguments='{"inventory_id":', index=0,
            ))
    try:
        outcome, sink, mongo = await _run(db_name, BadJsonModel())
        assert outcome.status == "failed"
        assert outcome.error_code == "REVIEW_FAILED"
        assert [item["status"] for kind, item in sink.events if kind == "tool_finished"] == ["error"]
        assert "INVALID_ARGUMENTS" in next(item["error"] for kind, item in sink.events if kind == "tool_finished")
    finally:
        mongo_admin.drop_database(db_name)


@pytest.mark.asyncio
async def test_wrong_fact_and_rejected_answer_are_never_published(db_name, mongo_admin):
    try:
        def respond(messages):
            if messages[-1].role == "tool":
                return [token("P001 在 W01 缺口999件。")]
            return [call_tool("inventory_get", {"inventory_id": "I001"})]
        outcome, sink, mongo = await _run(db_name, ScriptedModel(responder=respond))
        assert outcome.status == "failed"
        assert outcome.error_code == "FACT_CHECK_FAILED"
        assert not [payload for kind, payload in sink.events if kind == "token"]
    finally:
        mongo_admin.drop_database(db_name)


@pytest.mark.asyncio
async def test_active_deadline_expires_during_final_model_delta(db_name, mongo_admin):
    try:
        now = [0.0]
        class LateModel:
            async def stream(self, messages, tools, ctx):
                now[0] = 181.0
                yield token("已完成查询。")
        with pytest.raises(RunDeadlineExceeded):
            await _run(
                db_name, LateModel(), budget=RunBudget("run_test", max_active_seconds=180, monotonic=lambda: now[0])
            )
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
