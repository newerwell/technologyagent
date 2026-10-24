"""P04 订单草稿 Mongo 仓储。"""

from __future__ import annotations

from typing import Any

from pymongo.asynchronous.client_session import AsyncClientSession

from backend.app.contracts.domain import OrderDraft
from backend.app.repositories.indexes import DRAFTS
from backend.app.repositories.mongo import MongoResources


class DraftRepository:
    def __init__(self, mongo: MongoResources) -> None:
        self._mongo = mongo

    def _kwargs(self, session: AsyncClientSession | None) -> dict[str, Any]:
        return {"session": session} if session is not None else {}

    async def insert(self, draft: OrderDraft, *, session: AsyncClientSession | None = None) -> None:
        payload = draft.model_dump(mode="python", exclude={"id"})
        payload.update({"snapshot_versions": draft.snapshot_versions, "quote_snapshots": draft.quote_snapshots,
                        "created_at": draft.created_at, "updated_at": draft.updated_at})
        await self._mongo.db[DRAFTS].insert_one(
            {"_id": draft.id, **payload}, **self._kwargs(session)
        )

    async def get(self, owner_id: str, draft_id: str, *, session: AsyncClientSession | None = None) -> OrderDraft | None:
        doc = await self._mongo.db[DRAFTS].find_one(
            {"_id": draft_id, "owner_id": owner_id}, **self._kwargs(session)
        )
        if doc is None:
            return None
        snapshot_versions = doc.pop("snapshot_versions", {})
        quote_snapshots = doc.pop("quote_snapshots", {})
        doc.pop("workflow_run_id", None)
        created_at = doc.pop("created_at", None)
        updated_at = doc.pop("updated_at", None)
        doc["id"] = doc.pop("_id")
        draft = OrderDraft(**doc)
        return draft.model_copy(update={"snapshot_versions": snapshot_versions,
                                        "quote_snapshots": quote_snapshots,
                                        "created_at": created_at, "updated_at": updated_at})

    async def replace_version(
        self, draft: OrderDraft, expected_version: int, *, session: AsyncClientSession
    ) -> bool:
        payload = draft.model_dump(mode="python", exclude={"id", "schema_version"})
        payload.update({"snapshot_versions": draft.snapshot_versions, "quote_snapshots": draft.quote_snapshots,
                        "created_at": draft.created_at, "updated_at": draft.updated_at})
        result = await self._mongo.db[DRAFTS].update_one(
            {"_id": draft.id, "owner_id": draft.owner_id, "version": expected_version,
             "state": {"$in": ["draft", "pending_approval"]}},
            {"$set": payload},
            session=session,
        )
        return result.modified_count == 1

    async def list_owner(self, owner_id: str) -> list[OrderDraft]:
        cursor = self._mongo.db[DRAFTS].find({"owner_id": owner_id}).sort([("_id", 1)])
        result = []
        async for doc in cursor:
            snapshot_versions = doc.pop("snapshot_versions", {})
            quote_snapshots = doc.pop("quote_snapshots", {})
            doc.pop("workflow_run_id", None)
            created_at = doc.pop("created_at", None)
            updated_at = doc.pop("updated_at", None)
            doc["id"] = doc.pop("_id")
            draft = OrderDraft(**doc)
            result.append(draft.model_copy(update={"snapshot_versions": snapshot_versions,
                                                   "quote_snapshots": quote_snapshots,
                                                   "created_at": created_at, "updated_at": updated_at}))
        return result
