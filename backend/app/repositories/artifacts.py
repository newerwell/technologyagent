from __future__ import annotations

from typing import Any
from backend.app.repositories.mongo import MongoResources


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
