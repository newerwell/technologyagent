"""P04 操作认领和结果查询；业务副作用由 MutationService 的事务完成。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession

from backend.app.repositories.indexes import OPERATIONS
from backend.app.repositories.mongo import MongoResources

LEASE_SECONDS = 120


class OperationRepository:
    def __init__(self, mongo: MongoResources) -> None:
        self._mongo = mongo

    async def get_by_key(self, owner_id: str, action: str, key: str,
                         session: AsyncClientSession | None = None) -> dict[str, Any] | None:
        kwargs = {"session": session} if session is not None else {}
        return await self._mongo.db[OPERATIONS].find_one(
            {"owner_id": owner_id, "action": action, "idempotency_key": key}, **kwargs)

    async def get(self, owner_id: str, operation_id: str) -> dict[str, Any] | None:
        return await self._mongo.db[OPERATIONS].find_one(
            {"_id": operation_id, "owner_id": owner_id}
        )

    async def claim(self, owner_id: str, action: str, key: str, payload_hash: str,
                    now: datetime) -> tuple[dict[str, Any], bool]:
        operation_id = f"op_{uuid4().hex}"
        existing = await self.get_by_key(owner_id, action, key)
        if existing:
            if existing["payload_hash"] != payload_hash:
                return existing, False
            if existing["status"] in {"succeeded", "failed"}:
                return existing, False
            if existing.get("lease_expires_at", now) > now:
                return existing, False
            claimed = await self._mongo.db[OPERATIONS].find_one_and_update(
                {"_id": existing["_id"], "status": {"$in": ["processing", "outcome_unknown"]},
                 "lease_expires_at": {"$lte": now}},
                {"$set": {"status": "processing", "lease_owner": operation_id,
                          "lease_expires_at": now + timedelta(seconds=LEASE_SECONDS), "updated_at": now}},
                return_document=ReturnDocument.AFTER,
            )
            return (claimed or existing), claimed is not None
        doc = {"_id": operation_id, "owner_id": owner_id, "action": action,
               "idempotency_key": key, "payload_hash": payload_hash,
               "status": "processing", "lease_owner": operation_id,
               "lease_expires_at": now + timedelta(seconds=LEASE_SECONDS),
               "created_at": now, "updated_at": now}
        try:
            await self._mongo.db[OPERATIONS].insert_one(doc)
            return doc, True
        except Exception as exc:
            from pymongo.errors import DuplicateKeyError
            if not isinstance(exc, DuplicateKeyError):
                raise
            existing = await self.get_by_key(owner_id, action, key)
            if existing is None:
                raise
            return existing, existing.get("lease_owner") == operation_id

    async def mark_succeeded(self, operation_id: str, lease_owner: str, result: dict,
                             order_id: str, now: datetime, *, session: AsyncClientSession) -> None:
        await self._mongo.db[OPERATIONS].update_one(
            {"_id": operation_id, "lease_owner": lease_owner},
            {"$set": {"status": "succeeded", "result": result,
                      "order_id": order_id, "updated_at": now}}, session=session,
        )
