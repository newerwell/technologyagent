"""P03 每 run 短期 opaque MCP token 摘要存储。原始 token 只交给 MCP 客户端。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.app.repositories.indexes import MCP_SESSIONS, SCHEMA_VERSION
from backend.app.repositories.mongo import MongoResources


@dataclass(frozen=True, slots=True)
class McpIdentity:
    token_hash: str
    owner_id: str
    run_id: str
    actor: str
    created_at: datetime
    expires_at: datetime


class McpTokenRepository:
    def __init__(self, mongo: MongoResources) -> None:
        self._mongo = mongo

    @property
    def _collection(self):
        return self._mongo.db[MCP_SESSIONS]

    async def insert(self, identity: McpIdentity) -> None:
        await self._collection.insert_one(
            {
                "_id": identity.token_hash,
                "owner_id": identity.owner_id,
                "run_id": identity.run_id,
                "actor": identity.actor,
                "expires_at": identity.expires_at,
                "created_at": identity.created_at,
                "schema_version": SCHEMA_VERSION,
            }
        )

    async def find(self, token_hash: str) -> McpIdentity | None:
        doc = await self._collection.find_one({"_id": token_hash})
        if doc is None:
            return None
        return McpIdentity(
            token_hash=doc["_id"],
            owner_id=doc["owner_id"],
            run_id=doc["run_id"],
            actor=doc["actor"],
            created_at=doc["created_at"],
            expires_at=doc["expires_at"],
        )

    async def delete(self, token_hash: str) -> None:
        await self._collection.delete_one({"_id": token_hash})
