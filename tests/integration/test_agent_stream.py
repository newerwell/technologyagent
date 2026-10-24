"""P03-T04: GraphExecutor 错误映射到现有 run/event，不伪造 completed。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from backend.app.agent.graph import GraphExecutor
from backend.app.agent.local_tools import LocalToolRegistry
from backend.app.contracts.common import FixedClock, RequestContext
from backend.app.integrations.model import ModelProviderError
from backend.app.repositories.catalog import CatalogRepository
from backend.app.repositories.indexes import ensure_indexes
from backend.app.repositories.inventory import InventoryRepository
from backend.app.repositories.mongo import MongoResources
from backend.app.services.chat import ChatService
from backend.app.services.runs import RunService
from backend.app.services.seeding import seed
from tests.integration.conftest import make_settings


class FailingModel:
    async def stream(self, messages, tools, ctx):
        raise ModelProviderError("provider down", code="MODEL_UNAVAILABLE")
        yield  # pragma: no cover


async def test_model_failure_becomes_failed_run_with_error_event(db_name, mongo_admin):
    settings = make_settings(db_name)
    mongo = await MongoResources.open(settings)
    chat: ChatService | None = None
    try:
        await ensure_indexes(mongo.db)
        await seed(mongo.db, reset=True)
        clock = FixedClock(datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc))
        registry = LocalToolRegistry(CatalogRepository(mongo), InventoryRepository(mongo), clock)
        async def factory(_ctx):
            return registry
        runs = RunService(mongo, clock)
        chat = ChatService(
            runs,
            GraphExecutor(FailingModel(), factory, model_mode="live"),
            model_mode="live",
        )
        ctx = RequestContext(owner_id="local-owner", request_id="req-model-fail")
        run = await chat.start(None, "查库存", "req-model-fail", ctx)
        for _ in range(100):
            current = await runs.get(run.id, ctx)
            if current.status in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(0.01)
        assert current.status == "failed"
        assert current.error_code == "MODEL_UNAVAILABLE"
        events = await runs.events(run.id, 0, ctx)
        assert [event.type for event in events] == [
            "run_started", "error", "run_finished", "stream_end"
        ]
        assert events[1].payload["code"] == "MODEL_UNAVAILABLE"
        assert events[0].payload["model_mode"] == "live"
    finally:
        if chat is not None:
            await chat.shutdown()
        await mongo.close()
        mongo_admin.drop_database(db_name)
