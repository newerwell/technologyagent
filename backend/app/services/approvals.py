"""P04 人工决策服务：审批只绑定服务器草稿事实，不执行订单副作用。"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from backend.app.contracts.common import AppError, Clock, ErrorCodes, RequestContext
from backend.app.contracts.domain import OrderDraft
from backend.app.contracts.order_workflow import ResumeRequest
from backend.app.domain.orders import serialize_draft
from backend.app.repositories.drafts import DraftRepository
from backend.app.repositories.indexes import APPROVALS, SCHEMA_VERSION
from backend.app.repositories.mongo import MongoResources


def draft_hash(draft: OrderDraft) -> str:
    payload = {
        **draft.model_dump(mode="json", exclude={"state"}),
        "snapshot_versions": draft.snapshot_versions,
        "quote_snapshots": draft.quote_snapshots,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ApprovalService:
    def __init__(self, mongo: MongoResources, clock: Clock) -> None:
        self._mongo = mongo
        self._clock = clock
        self._drafts = DraftRepository(mongo)

    async def request(self, draft_id: str, run_id: str, ctx: RequestContext) -> dict:
        draft = await self._drafts.get(ctx.owner_id, draft_id)
        if draft is None:
            raise AppError(ErrorCodes.NOT_FOUND, "draft not found", http_status=404)
        if draft.state not in {"draft", "pending_approval"}:
            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "draft cannot be approved", http_status=409)
        pending = await self._mongo.db[APPROVALS].find_one(
            {"owner_id": ctx.owner_id, "draft_id": draft.id, "draft_version": draft.version,
             "payload_hash": draft_hash(draft), "status": "pending"}
        )
        if pending is not None:
            return {"approval_id": pending["_id"], "draft": serialize_draft(draft), "status": "pending"}
        now = self._clock.now()
        approval_id = f"apr_{uuid4().hex}"
        document = {
            "_id": approval_id, "owner_id": ctx.owner_id, "run_id": run_id,
            "draft_id": draft.id, "draft_version": draft.version,
            "action": "order_create", "payload_hash": draft_hash(draft),
            "status": "pending", "created_at": now, "updated_at": now,
            "schema_version": SCHEMA_VERSION,
        }
        try:
            async with self._mongo.transaction() as session:
                await self._mongo.db[APPROVALS].insert_one(document, session=session)
                await self._mongo.db["drafts"].update_one(
                    {"_id": draft.id, "owner_id": ctx.owner_id, "version": draft.version,
                     "state": {"$in": ["draft", "pending_approval"]}},
                    {"$set": {"state": "pending_approval", "updated_at": now}},
                    session=session,
                )
        except DuplicateKeyError:
            pending = await self._mongo.db[APPROVALS].find_one(
                {"owner_id": ctx.owner_id, "draft_id": draft.id, "draft_version": draft.version,
                 "payload_hash": draft_hash(draft), "status": "pending"}
            )
            if pending is None:
                raise
            return {"approval_id": pending["_id"], "draft": serialize_draft(draft), "status": "pending"}
        return {"approval_id": approval_id, "draft": serialize_draft(draft), "status": "pending"}

    async def resolve(self, approval_id: str, request: ResumeRequest, ctx: RequestContext) -> dict:
        doc = await self._mongo.db[APPROVALS].find_one({"_id": approval_id, "owner_id": ctx.owner_id})
        if doc is None:
            raise AppError(ErrorCodes.NOT_FOUND, "approval not found", http_status=404)
        draft_owner = await self._mongo.db["drafts"].find_one(
            {"_id": doc["draft_id"], "owner_id": ctx.owner_id}, {"workflow_run_id": 1}
        )
        workflow_run_id = (draft_owner or {}).get("workflow_run_id")
        if workflow_run_id and ctx.run_id != workflow_run_id:
            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT,
                           "workflow-owned approvals must be resolved through their owning run", http_status=409)
        draft = await self._drafts.get(ctx.owner_id, doc["draft_id"])
        if draft is None:
            raise AppError(ErrorCodes.NOT_FOUND, "draft not found", http_status=404)
        decision_hash = hashlib.sha256(json.dumps({
            "decision": request.decision, "expected_version": request.expected_version,
            "payload": request.payload,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if doc.get("decision") is not None:
            if (doc.get("decision_key") == request.idempotency_key
                    and doc.get("decision_payload_hash") == decision_hash
                    and doc.get("decision") == request.decision):
                return {"approval_id": approval_id,
                        "status": "approved" if request.decision == "approve" else "rejected",
                        "draft": serialize_draft(draft)}
            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "approval already has a different decision", http_status=409)
        if request.expected_version is not None and request.expected_version != draft.version:
            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "draft version is stale", http_status=409)
        if doc["draft_version"] != draft.version or doc["payload_hash"] != draft_hash(draft):
            await self._mongo.db[APPROVALS].update_one(
                {"_id": approval_id, "owner_id": ctx.owner_id, "status": "pending"},
                {"$set": {"status": "superseded", "updated_at": self._clock.now()}},
            )
            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "approval is superseded", http_status=409)
        if request.decision not in {"approve", "reject"}:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "edit and supplement must update draft first", http_status=422)
        status = "pending" if request.decision == "approve" else "rejected"
        now = self._clock.now()
        async with self._mongo.transaction() as session:
            result = await self._mongo.db[APPROVALS].update_one(
                {"_id": approval_id, "owner_id": ctx.owner_id, "status": "pending", "decision": {"$exists": False},
                 "draft_version": draft.version, "payload_hash": draft_hash(draft)},
                {"$set": {"status": status, "decision": request.decision,
                           "decision_key": request.idempotency_key,
                           "decision_payload_hash": decision_hash, "updated_at": now}},
                session=session,
            )
            if result.modified_count != 1:
                current = await self._mongo.db[APPROVALS].find_one({"_id": approval_id, "owner_id": ctx.owner_id}, session=session)
                if current and current.get("decision") == request.decision:
                    return {"approval_id": approval_id, "status": "approved" if request.decision == "approve" else "rejected", "draft": serialize_draft(draft)}
                raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "approval is no longer pending", http_status=409)
            await self._mongo.db["drafts"].update_one(
                {"_id": draft.id, "owner_id": ctx.owner_id, "version": draft.version},
                {"$set": {"state": "rejected" if status == "rejected" else "pending_approval", "updated_at": now}},
                session=session,
            )
        return {"approval_id": approval_id, "status": "approved" if request.decision == "approve" else "rejected", "draft": serialize_draft(draft)}
