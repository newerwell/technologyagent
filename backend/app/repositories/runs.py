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
            {"_id": thread_id, "owner_id": owner_id, "active_run_id": None},
            {"$set": {"active_run_id": run_id, "updated_at": now}},
            **self._kwargs(session),
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

    async def find_by_request(self, owner_id: str, request_id: str) -> dict[str, Any] | None:
        return await self._db[RUNS].find_one({"owner_id": owner_id, "request_id": request_id})

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
        session: AsyncClientSession,
    ) -> dict[str, Any] | None:
        return await self._db[RUNS].find_one_and_update(
            {"_id": run_id, "owner_id": owner_id},
            {
                "$set": {
                    "status": status,
                    "last_seq": last_seq,
                    "updated_at": now,
                    "finished_at": now,
                    "error_code": error_code,
                    "cancel_requested": False,
                }
            },
            return_document=ReturnDocument.AFTER,
            session=session,
        )

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
