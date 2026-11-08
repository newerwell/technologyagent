"""P04 操作认领和结果查询；业务副作用由 MutationService 的事务完成。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession

from backend.app.repositories.indexes import OPERATIONS
from backend.app.repositories.mongo import MongoResources
from backend.app.contracts.common import AppError, ErrorCodes

LEASE_SECONDS = 120


class OperationRepository:
    def __init__(self, mongo: MongoResources) -> None:
        self._mongo = mongo

    @staticmethod
    def remote_action_name(provider_scope: str, original_action: str) -> str:
        provider_key = hashlib.sha256(provider_scope.encode()).hexdigest()
        return f"remote:{provider_key}:{original_action}"

    async def get_by_key(self, owner_id: str, action: str, key: str,
                         session: AsyncClientSession | None = None) -> dict[str, Any] | None:
        kwargs = {"session": session} if session is not None else {}
        return await self._mongo.db[OPERATIONS].find_one(
            {"owner_id": owner_id, "action": action, "idempotency_key": key}, **kwargs)

    async def get(self, owner_id: str, operation_id: str) -> dict[str, Any] | None:
        return await self._mongo.db[OPERATIONS].find_one(
            {"_id": operation_id, "owner_id": owner_id}
        )

    async def get_remote_by_key(self, owner_id: str, provider_scope: str, original_action: str,
                                key: str, session: AsyncClientSession | None = None) -> dict[str, Any] | None:
        kwargs = {"session": session} if session is not None else {}
        return await self._mongo.db[OPERATIONS].find_one(
            {"owner_id": owner_id, "action": self.remote_action_name(provider_scope, original_action),
             "provider_scope": provider_scope,
             "original_action": original_action, "idempotency_key": key}, **kwargs)

    async def create_remote(self, document: dict[str, Any], *, session: AsyncClientSession) -> None:
        """Persist the remote intent inside the same transaction that consumes approval."""
        await self._mongo.db[OPERATIONS].insert_one(document, session=session)

    async def mark_remote_dispatched(self, operation_id: str, owner_id: str, now: datetime) -> bool:
        """Durably fence the one permitted POST before network dispatch."""
        updated = await self._mongo.db[OPERATIONS].update_one(
            {"_id": operation_id, "owner_id": owner_id, "provider_scope": {"$exists": True},
             "status": "processing", "dispatch_state": "not_dispatched"},
            {"$set": {"status": "outcome_unknown", "dispatch_state": "dispatched",
                      "dispatched_at": now, "updated_at": now}},
        )
        return updated.modified_count == 1

    async def mark_remote_unknown(self, operation_id: str, owner_id: str, now: datetime,
                                  error_code: str | None = None) -> None:
        values: dict[str, Any] = {"status": "outcome_unknown", "updated_at": now}
        if error_code:
            values["last_error_code"] = error_code
        await self._mongo.db[OPERATIONS].update_one(
            {"_id": operation_id, "owner_id": owner_id, "provider_scope": {"$exists": True},
             "status": {"$ne": "succeeded"}}, {"$set": values})

    async def mark_remote_succeeded(self, operation_id: str, owner_id: str, result: dict[str, Any],
                                    now: datetime) -> bool:
        updated = await self._mongo.db[OPERATIONS].update_one(
            {"_id": operation_id, "owner_id": owner_id, "provider_scope": {"$exists": True},
             "status": {"$in": ["processing", "outcome_unknown"]},
             "dispatch_state": "dispatched"},
            {"$set": {"status": "succeeded", "result": result,
                      "external_result": result, "external_id": result.get("id"),
                      "updated_at": now}},
        )
        return updated.modified_count == 1

    async def claim(self, owner_id: str, action: str, key: str, payload_hash: str,
                    now: datetime, *, run_id: str | None = None) -> tuple[dict[str, Any], bool]:
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
        if run_id is not None:
            doc["run_id"] = run_id
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
        updated = await self._mongo.db[OPERATIONS].update_one(
            {"_id": operation_id, "lease_owner": lease_owner, "status": "processing",
             "lease_expires_at": {"$gt": now}},
            {"$set": {"status": "succeeded", "result": result,
                      "order_id": order_id, "updated_at": now}}, session=session,
        )
        if updated.modified_count != 1:
            raise AppError(ErrorCodes.OUTCOME_UNKNOWN,
                           "operation lease expired or changed before commit", http_status=409)

    async def assert_lease(self, operation_id: str, lease_owner: str, now: datetime,
                           *, session: AsyncClientSession) -> None:
        """Write-fence the lease in the business transaction against a concurrent reclaim."""
        result = await self._mongo.db[OPERATIONS].update_one(
            {"_id": operation_id, "lease_owner": lease_owner, "status": "processing",
             "lease_expires_at": {"$gt": now}},
            {"$inc": {"lease_fence": 1}, "$set": {"updated_at": now}}, session=session,
        )
        if result.modified_count != 1:
            raise AppError(ErrorCodes.OUTCOME_UNKNOWN,
                           "operation lease is no longer owned by this executor", http_status=409)

    async def mark_failed(self, operation_id: str, lease_owner: str, error_code: str, now: datetime) -> None:
        await self._mongo.db[OPERATIONS].update_one(
            {"_id": operation_id, "lease_owner": lease_owner, "status": "processing"},
            {"$set": {"status": "failed", "error_code": error_code, "updated_at": now}},
        )
