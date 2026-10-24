"""P02 run/event/message 原子性与并发边界。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from backend.app.contracts.agent import ExecutionOutcome
from backend.app.contracts.common import AppError, ErrorCodes, FixedClock, RequestContext
from backend.app.repositories.indexes import ensure_indexes
from backend.app.repositories.mongo import MongoResources
from backend.app.services.runs import RunService
from tests.integration.conftest import make_settings

NOW = datetime(2026, 10, 24, 1, 0, 0, tzinfo=timezone.utc)


def ctx(owner: str = "owner-a", request_id: str = "request") -> RequestContext:
    return RequestContext(owner_id=owner, request_id=request_id)


async def make_service(db_name: str):
    settings = make_settings(db_name)
    mongo = await MongoResources.open(settings)
    await ensure_indexes(mongo.db)
    service = RunService(mongo, FixedClock(NOW))
    return mongo, service


async def test_request_id_is_idempotent_and_payload_conflict_is_409(db_name, mongo_admin):
    mongo, service = await make_service(db_name)
    try:
        first = await service.create(None, "hello", "req-1", ctx())
        same = await service.create(None, "hello", "req-1", ctx())
        assert same.id == first.id
        assert same.thread_id == first.thread_id
        with pytest.raises(AppError) as error:
            await service.create(None, "different", "req-1", ctx())
        assert error.value.code == ErrorCodes.IDEMPOTENCY_CONFLICT
        with pytest.raises(AppError) as error:
            await service.create(first.thread_id, "second", "req-2", ctx())
        assert error.value.code == ErrorCodes.ACTIVE_RUN_EXISTS
        assert await mongo.db["runs"].count_documents({}) == 1
        assert await mongo.db["messages"].count_documents({}) == 1
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)


async def test_concurrent_same_request_returns_one_created_run(db_name, mongo_admin):
    mongo, service = await make_service(db_name)
    try:
        outcomes = await asyncio.gather(
            service.create_or_get(None, "same", "same-request", ctx()),
            service.create_or_get(None, "same", "same-request", ctx()),
        )
        run_ids = {item[0].id for item in outcomes}
        flags = sorted(item[1] for item in outcomes)
        assert len(run_ids) == 1
        assert flags == [False, True]
        assert await mongo.db["runs"].count_documents({}) == 1
        assert await mongo.db["messages"].count_documents({}) == 1
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)


async def test_thread_has_only_one_active_run_under_race(db_name, mongo_admin):
    mongo, service = await make_service(db_name)
    try:
        first = await service.create(None, "first", "req-first", ctx())
        await service.finish(
            first.id,
            ExecutionOutcome(status="completed", summary="done"),
            ctx(),
        )
        outcomes = await asyncio.gather(
            service.create(first.thread_id, "a", "req-a", ctx()),
            service.create(first.thread_id, "b", "req-b", ctx()),
            return_exceptions=True,
        )
        successes = [item for item in outcomes if not isinstance(item, Exception)]
        errors = [item for item in outcomes if isinstance(item, Exception)]
        assert len(successes) == 1
        assert len(errors) == 1
        assert isinstance(errors[0], AppError)
        assert errors[0].code == ErrorCodes.ACTIVE_RUN_EXISTS
        assert await mongo.db["runs"].count_documents({"thread_id": first.thread_id, "status": "running"}) == 1
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)


async def test_append_event_increments_seq_atomically_and_finish_is_idempotent(
    db_name, mongo_admin
):
    mongo, service = await make_service(db_name)
    try:
        run = await service.create(None, "seq", "req-seq", ctx())
        run_ctx = RequestContext(owner_id="owner-a", request_id="req-seq", run_id=run.id)
        await asyncio.gather(
            *[
                service.append_event(
                    run.id,
                    "token",
                    {"message_id": "msg-" + str(index), "delta": str(index), "actor": "main"},
                    run_ctx,
                )
                for index in range(10)
            ]
        )
        events = await service.events(run.id, 0, ctx())
        assert [event.seq for event in events] == list(range(1, 11))
        assert len({event.event_id for event in events}) == 10

        finished = await service.finish(
            run.id, ExecutionOutcome(status="completed", summary="final"), run_ctx
        )
        assert finished.status == "completed"
        assert finished.last_seq == 12
        events = await service.events(run.id, 0, ctx())
        assert [event.seq for event in events] == list(range(1, 13))
        assert [event.type for event in events[-2:]] == ["run_finished", "stream_end"]
        assert await mongo.db["messages"].count_documents(
            {"run_id": run.id, "role": "assistant"}
        ) == 1
        thread_doc = await mongo.db["threads"].find_one({"_id": run.thread_id})
        assert thread_doc["active_run_id"] is None

        again = await service.finish(
            run.id, ExecutionOutcome(status="completed", summary="final"), run_ctx
        )
        assert again.status == "completed"
        assert await mongo.db["messages"].count_documents(
            {"run_id": run.id, "role": "assistant"}
        ) == 1
        assert (await mongo.db["runs"].find_one({"_id": run.id}))["last_seq"] == 12
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)


async def test_cancel_request_does_not_finish_terminal_run(db_name, mongo_admin):
    mongo, service = await make_service(db_name)
    try:
        run = await service.create(None, "cancel", "req-cancel", ctx())
        run_ctx = RequestContext(owner_id="owner-a", request_id="req-cancel", run_id=run.id)
        await service.append_event(
            run.id,
            "token",
            {"message_id": "msg", "delta": "a", "actor": "main"},
            run_ctx,
        )
        cancelled = await service.request_cancel(run.id, ctx())
        assert cancelled.cancel_requested is True
        assert "cancel" not in cancelled.available_actions
        await service.finish(
            run.id, ExecutionOutcome(status="cancelled", summary="cancelled"), run_ctx
        )
        terminal = await service.request_cancel(run.id, ctx())
        assert terminal.status == "cancelled"
        assert terminal.cancel_requested is False
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)


async def test_recover_orphan_marks_failed_and_releases_thread(db_name, mongo_admin):
    mongo, service = await make_service(db_name)
    try:
        run = await service.create(None, "orphan", "req-orphan", ctx())
        recovered = await service.recover_orphans()
        assert recovered == 1
        document = await mongo.db["runs"].find_one({"_id": run.id})
        assert document["status"] == "failed"
        assert document["error_code"] == "PROCESS_RESTARTED"
        assert document["finished_at"] is not None
        assert (await mongo.db["threads"].find_one({"_id": run.thread_id}))["active_run_id"] is None
        events = await service.events(run.id, 0, ctx())
        assert [event.type for event in events] == ["error", "run_finished", "stream_end"]
        assert events[0].payload["code"] == "PROCESS_RESTARTED"
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)


async def test_owner_isolation_and_delete_running_conflict(db_name, mongo_admin):
    mongo, service = await make_service(db_name)
    try:
        run = await service.create(None, "private", "req-private", ctx("owner-a"))
        with pytest.raises(AppError) as error:
            await service.get(run.id, ctx("owner-b"))
        assert error.value.code == ErrorCodes.NOT_FOUND
        with pytest.raises(AppError) as error:
            await service.get_conversation(run.thread_id, ctx("owner-b"))
        assert error.value.code == ErrorCodes.NOT_FOUND
        with pytest.raises(AppError) as error:
            await service.delete_conversation(run.thread_id, ctx("owner-a"))
        assert error.value.code == ErrorCodes.ACTIVE_RUN_EXISTS

        await service.finish(
            run.id,
            ExecutionOutcome(status="completed", summary="done"),
            RequestContext(owner_id="owner-a", request_id="req-private", run_id=run.id),
        )
        assert (await service.delete_conversation(run.thread_id, ctx("owner-a"))).deleted is True
        with pytest.raises(AppError):
            await service.get_conversation(run.thread_id, ctx("owner-a"))
        assert await mongo.db["messages"].count_documents({}) == 0
        assert await mongo.db["events"].count_documents({}) == 0
        assert await mongo.db["runs"].count_documents({}) == 0
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)

async def test_delete_claim_prevents_deleting_a_new_run(db_name, mongo_admin):
    mongo, service = await make_service(db_name)
    try:
        run = await service.create(None, "old", "req-old", ctx())
        await service.finish(
            run.id,
            ExecutionOutcome(status="completed", summary="old done"),
            RequestContext(owner_id="owner-a", request_id="req-old", run_id=run.id),
        )

        original_get_thread = service._runs.get_thread
        entered = asyncio.Event()
        release = asyncio.Event()
        paused = False

        async def paused_get_thread(owner_id, thread_id, *, session=None):
            nonlocal paused
            document = await original_get_thread(
                owner_id, thread_id, session=session
            )
            if not paused:
                paused = True
                entered.set()
                await release.wait()
            return document

        service._runs.get_thread = paused_get_thread
        delete_task = asyncio.create_task(
            service.delete_conversation(run.thread_id, ctx())
        )
        await asyncio.wait_for(entered.wait(), timeout=5)

        new_run = await service.create(run.thread_id, "new", "req-new", ctx())
        release.set()
        with pytest.raises(AppError) as error:
            await delete_task
        assert error.value.code == ErrorCodes.ACTIVE_RUN_EXISTS
        assert await mongo.db["runs"].find_one({"_id": new_run.id}) is not None
        thread = await mongo.db["threads"].find_one({"_id": run.thread_id})
        assert thread["active_run_id"] == new_run.id
        assert await mongo.db["messages"].count_documents({"thread_id": run.thread_id}) == 3
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)


async def test_same_request_on_existing_idle_thread_race_is_idempotent(
    db_name, mongo_admin
):
    mongo, service = await make_service(db_name)
    try:
        seed_run = await service.create(None, "seed", "req-seed", ctx())
        await service.finish(
            seed_run.id,
            ExecutionOutcome(status="completed", summary="seed"),
            ctx(),
        )
        original_find = service._runs.find_by_request
        entered = asyncio.Event()
        release = asyncio.Event()
        initial_reads = 0

        async def paused_find(owner_id, request_id, *, session=None):
            nonlocal initial_reads
            if session is None and request_id == "req-race" and initial_reads < 2:
                initial_reads += 1
                if initial_reads == 2:
                    entered.set()
                await release.wait()
                return None
            return await original_find(owner_id, request_id, session=session)

        service._runs.find_by_request = paused_find
        first = asyncio.create_task(
            service.create_or_get(seed_run.thread_id, "same", "req-race", ctx())
        )
        second = asyncio.create_task(
            service.create_or_get(seed_run.thread_id, "same", "req-race", ctx())
        )
        await asyncio.wait_for(entered.wait(), timeout=5)
        release.set()
        outcomes = await asyncio.gather(first, second)
        assert {item[0].id for item in outcomes} == {outcomes[0][0].id}
        assert sorted(item[1] for item in outcomes) == [False, True]
        assert await mongo.db["runs"].count_documents(
            {"thread_id": seed_run.thread_id, "request_id": "req-race"}
        ) == 1
        assert await mongo.db["messages"].count_documents(
            {"thread_id": seed_run.thread_id, "role": "user", "content": "same"}
        ) == 1
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)

async def test_create_after_delete_cannot_leave_orphan_run(db_name, mongo_admin):
    mongo, service = await make_service(db_name)
    try:
        run = await service.create(None, "delete me", "req-delete", ctx())
        await service.finish(
            run.id,
            ExecutionOutcome(status="completed", summary="done"),
            ctx(),
        )
        assert (await service.delete_conversation(run.thread_id, ctx())).deleted is True
        with pytest.raises(AppError) as error:
            await service.create(run.thread_id, "after delete", "req-after", ctx())
        assert error.value.code == ErrorCodes.NOT_FOUND
        assert await mongo.db["runs"].count_documents({"thread_id": run.thread_id}) == 0
        assert await mongo.db["messages"].count_documents({"thread_id": run.thread_id}) == 0
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)
