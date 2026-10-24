"""P02 展示消息持久化：user 消息一次插入，assistant 最终消息按固定 _id 幂等插入。"""

from __future__ import annotations

from datetime import datetime

from pymongo.asynchronous.client_session import AsyncClientSession

from backend.app.repositories.indexes import MESSAGES, SCHEMA_VERSION
from backend.app.repositories.mongo import MongoResources


class MessageRepository:
    def __init__(self, mongo: MongoResources) -> None:
        self._mongo = mongo

    @property
    def _db(self):
        return self._mongo.db

    def _kwargs(self, session: AsyncClientSession | None):
        return {"session": session} if session is not None else {}

    async def insert_user(
        self,
        *,
        message_id: str,
        thread_id: str,
        run_id: str,
        owner_id: str,
        content: str,
        created_at: datetime,
        session: AsyncClientSession | None = None,
    ) -> None:
        await self._db[MESSAGES].insert_one(
            {
                "_id": message_id,
                "thread_id": thread_id,
                "run_id": run_id,
                "owner_id": owner_id,
                "role": "user",
                "content": content,
                "created_at": created_at,
                "schema_version": SCHEMA_VERSION,
            },
            **self._kwargs(session),
        )

    async def upsert_final(
        self,
        *,
        message_id: str,
        thread_id: str,
        run_id: str,
        owner_id: str,
        content: str,
        created_at: datetime,
        session: AsyncClientSession | None = None,
    ) -> None:
        await self._db[MESSAGES].update_one(
            {"_id": message_id},
            {
                "$setOnInsert": {
                    "_id": message_id,
                    "thread_id": thread_id,
                    "run_id": run_id,
                    "owner_id": owner_id,
                    "role": "assistant",
                    "content": content,
                    "created_at": created_at,
                    "schema_version": SCHEMA_VERSION,
                }
            },
            upsert=True,
            **self._kwargs(session),
        )

    async def list_thread(self, owner_id: str, thread_id: str):
        cursor = self._db[MESSAGES].find(
            {"owner_id": owner_id, "thread_id": thread_id}
        ).sort([("created_at", 1), ("_id", 1)])
        return [doc async for doc in cursor]

    async def delete_thread(
        self, owner_id: str, thread_id: str, *, session: AsyncClientSession | None = None
    ) -> int:
        result = await self._db[MESSAGES].delete_many(
            {"owner_id": owner_id, "thread_id": thread_id},
            **self._kwargs(session),
        )
        return result.deleted_count
