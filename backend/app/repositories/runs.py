"""P02 run/event/thread 持久化：事务由 RunService 组合多集合操作。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pymongo import ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession

from backend.app.repositories.indexes import EVENTS, RUNS, SCHEMA_VERSION, THREADS
from backend.app.repositories.mongo import MongoResources


class RunRepository:
    def __init__(self, mongo: MongoResources) -> None:
        self._mongo = mongo

    @property
    def _db(self):
        return self._mongo.db

    def _kwargs(self, session: AsyncClientSession | None):
        return {"session": session} if session is not None else {}

    async def get_thread(
        self, owner_id: str, thread_id: str, *, session: AsyncClientSession | None = None
    ) -> dict[str, Any] | None:
        return await self._db[THREADS].find_one(
            {"_id": thread_id, "owner_id": owner_id}, **self._kwargs(session)
        )

    async def list_threads(self, owner_id: str) -> list[dict[str, Any]]:
        cursor = (
            self._db[THREADS]
            .find({"owner_id": owner_id})
            .sort([("updated_at", -1), ("_id", -1)])
            .limit(50)
        )
        return [doc async for doc in cursor]

    async def insert_thread(self, document: dict[str, Any], *, session: AsyncClientSession | None = None) -> None:
        await self._db[THREADS].insert_one(document, **self._kwargs(session))

    async def claim_thread(
        self,
        owner_id: str,
        thread_id: str,
        run_id: str,
        now: datetime,
        *,
        session: AsyncClientSession | None = None,
    ) -> bool:
        result = await self._db[THREADS].update_one(
            {
                "_id": thread_id,
                "owner_id": owner_id,
                "active_run_id": None,
                "deleting": {"$ne": True},
            },
            {"$set": {"active_run_id": run_id, "updated_at": now}},
            **self._kwargs(session),
        )
        return result.modified_count == 1

    async def claim_for_delete(
        self,
        owner_id: str,
        thread_id: str,
        now: datetime,
        *,
        session: AsyncClientSession,
    ) -> bool:
        """与 claim_thread 在同一 thread 文档上竞争；只有成功者能删除。"""
        result = await self._db[THREADS].update_one(
            {
                "_id": thread_id,
                "owner_id": owner_id,
                "active_run_id": None,
                "deleting": {"$ne": True},
            },
            {"$set": {"deleting": True, "updated_at": now}},
            session=session,
        )
        return result.modified_count == 1

    async def release_thread(
        self,
        owner_id: str,
        thread_id: str,
        run_id: str,
        now: datetime,
        *,
        session: AsyncClientSession | None = None,
    ) -> None:
        await self._db[THREADS].update_one(
            {"_id": thread_id, "owner_id": owner_id, "active_run_id": run_id},
            {"$set": {"active_run_id": None, "updated_at": now}},
            **self._kwargs(session),
        )

    async def update_thread_touch(
        self,
        owner_id: str,
        thread_id: str,
        now: datetime,
        *,
        session: AsyncClientSession | None = None,
    ) -> None:
        await self._db[THREADS].update_one(
            {"_id": thread_id, "owner_id": owner_id},
            {"$set": {"updated_at": now}},
            **self._kwargs(session),
        )

    async def insert_run(self, document: dict[str, Any], *, session: AsyncClientSession | None = None) -> None:
        await self._db[RUNS].insert_one(document, **self._kwargs(session))

    async def get_run(
        self, owner_id: str, run_id: str, *, session: AsyncClientSession | None = None
    ) -> dict[str, Any] | None:
        return await self._db[RUNS].find_one(
            {"_id": run_id, "owner_id": owner_id}, **self._kwargs(session)
        )

    async def find_by_request(
        self,
        owner_id: str,
        request_id: str,
        *,
        session: AsyncClientSession | None = None,
    ) -> dict[str, Any] | None:
        return await self._db[RUNS].find_one(
            {"owner_id": owner_id, "request_id": request_id},
            **self._kwargs(session),
        )

    async def latest_run_for_thread(self, owner_id: str, thread_id: str) -> dict[str, Any] | None:
        cursor = (
            self._db[RUNS]
            .find({"owner_id": owner_id, "thread_id": thread_id})
            .sort([("created_at", -1), ("_id", -1)])
            .limit(1)
        )
        async for doc in cursor:
            return doc
        return None

    async def bump_seq(
        self, owner_id: str, run_id: str, *, session: AsyncClientSession
    ) -> dict[str, Any] | None:
        return await self._db[RUNS].find_one_and_update(
            {
                "_id": run_id,
                "owner_id": owner_id,
                "status": {"$in": ["created", "running"]},
            },
            {"$inc": {"last_seq": 1}},
            return_document=ReturnDocument.AFTER,
            session=session,
        )

    async def update_harness_state(
        self,
        owner_id: str,
        run_id: str,
        fields: dict[str, Any],
        *,
        session: AsyncClientSession,
    ) -> bool:
        result = await self._db[RUNS].update_one(
            {"_id": run_id, "owner_id": owner_id, "status": {"$in": ["created", "running"]}},
            {"$set": fields},
            session=session,
        )
        return result.matched_count == 1

    async def insert_event(
        self, document: dict[str, Any], *, session: AsyncClientSession | None = None
    ) -> None:
        await self._db[EVENTS].insert_one(document, **self._kwargs(session))

    async def list_events(self, owner_id: str, run_id: str, after_seq: int) -> list[dict[str, Any]]:
        cursor = (
            self._db[EVENTS]
            .find({"owner_id": owner_id, "run_id": run_id, "seq": {"$gt": after_seq}})
            .sort([("seq", 1)])
        )
        return [doc async for doc in cursor]

    async def update_terminal(
        self,
        owner_id: str,
        run_id: str,
        *,
        status: str,
        last_seq: int,
        now: datetime,
        error_code: str | None,
        summary: str,
        committed_facts: bool,
        active_seconds_used: float,
        expected_statuses: list[str] | None = None,
        session: AsyncClientSession,
    ) -> dict[str, Any] | None:
        return await self._db[RUNS].find_one_and_update(
            {"_id": run_id, "owner_id": owner_id,
             **({"status": {"$in": expected_statuses}} if expected_statuses else {})},
            {
                "$set": {
                    "status": status,
                    "last_seq": last_seq,
                    "updated_at": now,
                    "finished_at": now,
                    "error_code": error_code,
                    "summary": summary,
                    "committed_facts": committed_facts,
                    "active_seconds_used": active_seconds_used,
                    "active_started_at": None,
                    "cancel_requested": False,
                    "pending_interrupt": None,
                }
            },
            return_document=ReturnDocument.AFTER,
            session=session,
        )

    async def update_waiting(
        self, owner_id: str, run_id: str, *, interrupt: dict[str, Any], last_seq: int,
        active_seconds_used: float, now: datetime, session: AsyncClientSession,
    ) -> dict[str, Any] | None:
        return await self._db[RUNS].find_one_and_update(
            {"_id": run_id, "owner_id": owner_id, "status": "running"},
            {"$set": {"status": "waiting_input", "pending_interrupt": interrupt,
                      "active_seconds_used": active_seconds_used,
                      "active_started_at": None,
                      "last_seq": last_seq, "updated_at": now}},
            return_document=ReturnDocument.AFTER, session=session,
        )

    async def resume_waiting(
        self, owner_id: str, run_id: str, interrupt_id: str, now: datetime,
        *, session: AsyncClientSession,
    ) -> dict[str, Any] | None:
        return await self._db[RUNS].find_one_and_update(
            {"_id": run_id, "owner_id": owner_id, "status": "waiting_input",
             "pending_interrupt.interrupt_id": interrupt_id},
            {"$set": {"status": "running", "pending_interrupt": None, "updated_at": now}},
            return_document=ReturnDocument.AFTER, session=session,
        )

    async def claim_resume(
        self, owner_id: str, run_id: str, interrupt_id: str, expected_version: int | None,
        resume_request: dict[str, Any], now: datetime, *, session: AsyncClientSession,
    ) -> dict[str, Any] | None:
        query: dict[str, Any] = {
            "_id": run_id, "owner_id": owner_id, "status": "waiting_input",
            "pending_interrupt.interrupt_id": interrupt_id,
        }
        if expected_version is not None:
            query["pending_interrupt.version"] = expected_version
        history = await self._db[RUNS].find_one(
            {"_id": run_id, "owner_id": owner_id},
            {"decision_history": 1}, session=session,
        )
        decisions = list((history or {}).get("decision_history") or [])
        decisions.append({
            "idempotency_key": resume_request.get("idempotency_key"),
            "request_hash": resume_request.get("request_hash"),
            "interrupt_id": interrupt_id,
            "state": "claimed",
            "request": resume_request,
            "result": None,
        })
        return await self._db[RUNS].find_one_and_update(
            query,
            {"$set": {"status": "running", "pending_interrupt": None,
                      "active_started_at": now,
                      "resume_request": resume_request, "decision_history": decisions,
                      "updated_at": now}},
            return_document=ReturnDocument.AFTER, session=session,
        )

    async def record_decision_result(
        self, owner_id: str, run_id: str, idempotency_key: str, result: dict[str, Any], now: datetime
    ) -> bool:
        updated = await self._db[RUNS].update_one(
            {"_id": run_id, "owner_id": owner_id,
             "decision_history.idempotency_key": idempotency_key},
            {"$set": {
                "decision_history.$.state": "completed",
                "decision_history.$.result": result,
                "updated_at": now,
            }},
        )
        return updated.modified_count == 1

    async def increment_usage(
        self, owner_id: str, run_id: str, field: str, *, limit: int
    ) -> bool:
        result = await self._db[RUNS].update_one(
            {
                "_id": run_id,
                "owner_id": owner_id,
                "status": "running",
                field: {"$lt": limit},
            },
            {"$inc": {field: 1}},
        )
        return result.modified_count == 1

    async def set_cancel_requested(
        self, owner_id: str, run_id: str, now: datetime
    ) -> dict[str, Any] | None:
        return await self._db[RUNS].find_one_and_update(
            {
                "_id": run_id,
                "owner_id": owner_id,
                "status": {"$in": ["created", "running"]},
            },
            {"$set": {"cancel_requested": True, "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )

    async def list_nonterminal(self) -> list[dict[str, Any]]:
        cursor = self._db[RUNS].find(
            {"status": {"$in": ["created", "running", "waiting_input"]}}
        )
        return [doc async for doc in cursor]

    async def delete_by_thread(
        self, owner_id: str, thread_id: str, *, session: AsyncClientSession
    ) -> None:
        await self._db[EVENTS].delete_many(
            {"owner_id": owner_id, "thread_id": thread_id}, session=session
        )
        await self._db[RUNS].delete_many(
            {"owner_id": owner_id, "thread_id": thread_id}, session=session
        )

    async def delete_thread(
        self, owner_id: str, thread_id: str, *, session: AsyncClientSession
    ) -> None:
        await self._db[THREADS].delete_one(
            {"_id": thread_id, "owner_id": owner_id}, session=session
        )
