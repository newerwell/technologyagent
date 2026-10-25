"""Mongo中按owner隔离的显式偏好。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.repositories.mongo import MongoResources


class PreferenceRepository:
    def __init__(self, mongo: MongoResources):
        self._mongo = mongo

    async def list(self, owner_id: str) -> dict[str, Any]:
        rows = await self._mongo.db["preferences"].find({"owner_id": owner_id}).to_list(length=20)
        return {row["key"]: row["value"] for row in rows}

    async def remember(self, owner_id: str, key: str, value: Any, now: datetime) -> dict[str, Any]:
        await self._mongo.db["preferences"].update_one(
            {"owner_id": owner_id, "key": key},
            {"$set": {"value": value, "updated_at": now, "explicit": True},
             "$setOnInsert": {"owner_id": owner_id, "key": key, "created_at": now}},
            upsert=True,
        )
        return {"key": key, "value": value, "updated_at": now, "explicit": True}

    async def delete(self, owner_id: str, key: str) -> bool:
        result = await self._mongo.db["preferences"].delete_one({"owner_id": owner_id, "key": key})
        return result.deleted_count == 1
