"""Receipt and inventory movement persistence contracts."""

from __future__ import annotations

from typing import Any

from backend.app.repositories.indexes import MOVEMENTS, RECEIPTS
from backend.app.repositories.mongo import MongoResources


class MovementRepository:
    def __init__(self, mongo: MongoResources) -> None:
        self.mongo = mongo

    async def receipt(self, owner_id: str, provider: str, receipt_id: str, *, session=None) -> dict[str, Any] | None:
        return await self.mongo.db[RECEIPTS].find_one(
            {"owner_id": owner_id, "provider": provider, "receipt_id": receipt_id}, session=session)

    async def movements_for_operation(self, operation_id: str) -> list[dict[str, Any]]:
        return [doc async for doc in self.mongo.db[MOVEMENTS].find({"operation_id": operation_id}).sort("line_index", 1)]
