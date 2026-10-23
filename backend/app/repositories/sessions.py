"""本地会话摘要持久化。原始 token 只存在于浏览器 Cookie。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.app.repositories.indexes import SCHEMA_VERSION, SESSIONS
from backend.app.repositories.mongo import MongoResources


@dataclass(frozen=True, slots=True)
class SessionRecord:
    token_hash: str
    owner_id: str
    created_at: datetime
    expires_at: datetime


class SessionRepository:
    def __init__(self, mongo: MongoResources) -> None:
        self._mongo = mongo

    @property
    def _collection(self):
        return self._mongo.db[SESSIONS]

    async def insert(self, record: SessionRecord) -> None:
        await self._collection.insert_one(
            {
                "_id": record.token_hash,
                "owner_id": record.owner_id,
                "created_at": record.created_at,
                "expires_at": record.expires_at,
                "schema_version": SCHEMA_VERSION,
            }
        )

    async def find(self, token_hash: str) -> SessionRecord | None:
        doc = await self._collection.find_one({"_id": token_hash})
        if doc is None:
            return None
        return SessionRecord(
            token_hash=doc["_id"],
            owner_id=doc["owner_id"],
            created_at=doc["created_at"],
            expires_at=doc["expires_at"],
        )
