from __future__ import annotations

from typing import Any
from backend.app.repositories.mongo import MongoResources
from backend.app.repositories.indexes import ARTIFACTS, RUNS, THREADS


class ArtifactRepository:
    def __init__(self, mongo: MongoResources) -> None:
        self._mongo = mongo

    @property
    def collection(self):
        return self._mongo.db["artifacts"]

    async def insert(self, document: dict[str, Any]) -> None:
        await self.collection.insert_one(document)

    async def get(self, artifact_id: str, owner_id: str) -> dict[str, Any] | None:
        return await self.collection.find_one({"_id": artifact_id, "owner_id": owner_id})

    async def list_for_thread(self, owner_id: str, thread_id: str) -> list[dict[str, Any]] | None:
        thread = await self._mongo.db[THREADS].find_one({"_id": thread_id, "owner_id": owner_id}, {"_id": 1})
        if thread is None:
            return None
        run_cursor = self._mongo.db[RUNS].find(
            {"owner_id": owner_id, "thread_id": thread_id}, {"_id": 1}
        )
        run_ids = [row["_id"] async for row in run_cursor]
        if not run_ids:
            return []
        cursor = self._mongo.db[ARTIFACTS].find(
            {"owner_id": owner_id, "run_id": {"$in": run_ids}, "status": "ready"},
            {"storage_key": 0},
        ).sort([("created_at", 1), ("_id", 1)])
        return [row async for row in cursor]
