"""P04 人工决策服务：审批只绑定服务器草稿事实，不执行订单副作用。"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from backend.app.contracts.common import AppError, Clock, ErrorCodes, RequestContext
from backend.app.contracts.domain import OrderDraft, Quote
from backend.app.domain.orders import quote_snapshot
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

    async def request_mutation(self, action: str, payload: dict, ctx: RequestContext,
                               *, proposal_id: str | None = None, source_refs: list[dict] | None = None) -> dict:
        """Create a versioned generic mutation proposal in the shared approval collection."""
        if not action or action == "order_create":
            raise AppError(ErrorCodes.VALIDATION_ERROR, "generic mutation action is invalid", 422)
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload_hash = hashlib.sha256(canonical.encode()).hexdigest()
        fact_snapshot: dict[str, object] = {}
        if action == "order_update":
            items = payload.get("items")
            if not isinstance(items, list) or not items:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "amendment items are required", 422)
            quote_hashes: dict[str, str] = {}
            for item in items:
                quote_id = item.get("quote_id") if isinstance(item, dict) else None
                quote_doc = await self._mongo.db["quotes"].find_one({"_id": quote_id}) if isinstance(quote_id, str) else None
                if quote_doc is None:
                    raise AppError(ErrorCodes.VALIDATION_ERROR, "amendment quote is unavailable", 409)
                quote_values = dict(quote_doc)
                quote_values["id"] = quote_values.pop("_id")
                quote_hashes[quote_id] = quote_snapshot(Quote(**quote_values))
            fact_snapshot["quote_hashes"] = quote_hashes
        proposal_id = proposal_id or f"proposal_{uuid4().hex}"
        approval_id = f"apr_{uuid4().hex}"
        now = self._clock.now()
        document = {"_id": approval_id, "owner_id": ctx.owner_id, "run_id": ctx.run_id,
                    "draft_id": proposal_id, "proposal_id": proposal_id, "proposal_payload": payload,
                    "draft_version": 1, "version": 1, "action": action, "payload_hash": payload_hash,
                    "source_refs": source_refs or [], "fact_snapshot": fact_snapshot,
                    "status": "pending", "created_at": now,
                    "updated_at": now, "schema_version": SCHEMA_VERSION}
        await self._mongo.db[APPROVALS].insert_one(document)
        return {"proposal_id": proposal_id, "approval_id": approval_id, "action": action,
                "payload": payload, "payload_hash": payload_hash, "version": 1,
                "status": "pending", "source_refs": source_refs or []}

    async def resolve_mutation(self, approval_id: str, decision: str, decision_key: str,
                               ctx: RequestContext, *, expected_version: int = 1) -> dict:
        if decision not in {"approve", "reject"} or not decision_key:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "decision and decision key are required", 422)
        doc = await self._mongo.db[APPROVALS].find_one({"_id": approval_id, "owner_id": ctx.owner_id})
        if doc is None or "proposal_payload" not in doc:
            raise AppError(ErrorCodes.NOT_FOUND, "mutation proposal not found", 404)
        if doc.get("decision") is not None:
            if doc.get("decision_key") == decision_key and doc.get("decision") == decision:
                return {"approval_id": approval_id, "status": "approved" if decision == "approve" else "rejected"}
            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "proposal already has a different decision", 409)
        if doc.get("version") != expected_version:
            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "proposal version is stale", 409)
        now = self._clock.now()
        status = "pending" if decision == "approve" else "rejected"
        result = await self._mongo.db[APPROVALS].update_one(
            {"_id": approval_id, "owner_id": ctx.owner_id, "status": "pending", "version": expected_version,
             "decision": {"$exists": False}},
            {"$set": {"status": status, "decision": decision, "decision_key": decision_key,
                       "updated_at": now}},
        )
        if result.modified_count != 1:
            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "proposal decision raced", 409)
        return {"approval_id": approval_id, "status": "approved" if decision == "approve" else "rejected"}

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
