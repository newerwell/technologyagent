"""P02-R04：run_started 窗口内的取消必须终止后续 token/工具。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from backend.app.agent.fake_executor import FakeAgent
from backend.app.contracts.common import FixedClock, RequestContext
from backend.app.repositories.indexes import ensure_indexes
from backend.app.repositories.mongo import MongoResources
from backend.app.services.chat import ChatService
from backend.app.services.runs import RunService
from tests.integration.conftest import make_settings


async def test_cancel_between_create_and_run_started_prevents_followup_steps(
    db_name, mongo_admin
):
    settings = make_settings(db_name)
    mongo = await MongoResources.open(settings)
    chat: ChatService | None = None
    try:
        await ensure_indexes(mongo.db)
        runs = RunService(
            mongo, FixedClock(datetime(2026, 10, 24, 3, 0, 0, tzinfo=timezone.utc))
        )
        chat = ChatService(runs, FakeAgent(token_delay=0.001))
        original_append = runs.append_event
        entered = asyncio.Event()
        release = asyncio.Event()

        async def paused_append(run_id, kind, payload, ctx):
            if kind == "run_started":
                entered.set()
                await release.wait()
            return await original_append(run_id, kind, payload, ctx)

        runs.append_event = paused_append
        ctx = RequestContext(owner_id="owner-a", request_id="req-window")
        start_task = asyncio.create_task(
            chat.start(None, "窗口取消", "req-window", ctx)
        )
        await asyncio.wait_for(entered.wait(), timeout=5)
        document = await mongo.db["runs"].find_one({"request_id": "req-window"})
        assert document is not None
        cancel = await chat.cancel(document["_id"], ctx)
        assert cancel.cancel_requested is True
        release.set()
        run = await start_task
        for _ in range(100):
            current = await runs.get(run.id, ctx)
            if current.status in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(0.01)
        assert current.status == "cancelled"
        events = await runs.events(run.id, 0, ctx)
        assert [event.type for event in events] == [
            "run_started",
            "run_finished",
            "stream_end",
        ]
        assert all(event.type not in {"token", "tool_started", "tool_finished"} for event in events)
    finally:
        if chat is not None:
            await chat.shutdown()
        await mongo.close()
        mongo_admin.drop_database(db_name)
