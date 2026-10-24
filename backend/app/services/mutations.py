"""P04 订单批准执行器：操作租约与订单/inbound/审批结果事务。"""

from __future__ import annotations

import hashlib
import json
import asyncio
from datetime import datetime
from typing import Callable

from pymongo.errors import DuplicateKeyError, OperationFailure

from backend.app.contracts.common import AppError, Clock, ErrorCodes, RequestContext
from backend.app.contracts.domain import Inventory, Quote, Supplier
from backend.app.services.approvals import draft_hash
from backend.app.domain.orders import quote_snapshot
from backend.app.repositories.drafts import DraftRepository
from backend.app.repositories.indexes import APPROVALS, INVENTORIES, PARTS, QUOTES, RUNS, SUPPLIERS
from backend.app.repositories.mongo import MongoResources
from backend.app.repositories.operations import OperationRepository
from backend.app.repositories.inventory import InventoryRepository
from backend.app.repositories.orders import OrderRepository


FaultHook = Callable[[str], None]


class MutationService:
    def __init__(self, mongo: MongoResources, clock: Clock, inventory: InventoryRepository,
                 orders: OrderRepository, fault_hook: FaultHook | None = None) -> None:
        self._mongo, self._clock, self._fault_hook = mongo, clock, fault_hook
        self._drafts = DraftRepository(mongo)
        self._operations = OperationRepository(mongo)
        self._inventory, self._orders = inventory, orders

    def _fault(self, point: str) -> None:
        if self._fault_hook:
            self._fault_hook(point)

    async def _supersede_changed_snapshot(self, draft, approval_id: str, ctx: RequestContext, now) -> None:
        stale = False
        for item in draft.items:
            quote_doc = await self._mongo.db[QUOTES].find_one({"_id": item.quote_id})
            inventory_doc = await self._mongo.db[INVENTORIES].find_one(
                {"part_id": item.part_id, "warehouse_id": draft.warehouse_id}
            )
            if quote_doc is None or inventory_doc is None:
                stale = True
                break
            quote_values = dict(quote_doc)
            quote_values["id"] = quote_values.pop("_id")
            try:
                quote = Quote(**quote_values)
            except Exception:
                stale = True
                break
            supplier_doc = await self._mongo.db[SUPPLIERS].find_one({"_id": quote.supplier_id})
            if (quote_snapshot(quote) != draft.quote_snapshots.get(quote.id)
                    or quote.valid_until <= now or supplier_doc is None
                    or supplier_doc.get("status") != "active"
                    or inventory_doc.get("_id") not in draft.snapshot_versions
                    or inventory_doc.get("version") != draft.snapshot_versions.get(inventory_doc.get("_id"))):
                stale = True
                break
        if not stale:
            return
        async with self._mongo.transaction() as session:
            await self._mongo.db[APPROVALS].update_one(
                {"_id": approval_id, "owner_id": ctx.owner_id, "status": "pending"},
                {"$set": {"status": "superseded", "updated_at": now}}, session=session,
            )
            await self._mongo.db["drafts"].update_one(
                {"_id": draft.id, "owner_id": ctx.owner_id, "version": draft.version,
                 "state": "pending_approval"},
                {"$set": {"state": "superseded", "updated_at": now}}, session=session,
            )
        raise AppError(ErrorCodes.STALE_APPROVAL,
                       "quote or inventory changed; a new draft confirmation is required", http_status=409)

    async def execute(self, draft_id: str, approval_id: str, idempotency_key: str,
                      ctx: RequestContext) -> dict:
        payload_hash = hashlib.sha256(json.dumps(
            {"draft_id": draft_id, "approval_id": approval_id}, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()
        now = self._clock.now()
        # A committed idempotent result must be replayed before inspecting an
        # approval that the successful transaction has already consumed.
        existing = await self._operations.get_by_key(ctx.owner_id, "order_create", idempotency_key)
        if existing and existing.get("payload_hash") != payload_hash:
            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "idempotency key payload differs", http_status=409)
        if existing and existing.get("status") == "succeeded":
            return existing["result"]

        # Reject an unapproved direct HTTP/MCP call before it can leave an
        # operation lease behind. The transaction repeats every check below.
        draft_before_claim = await self._drafts.get(ctx.owner_id, draft_id)
        approval_before_claim = await self._mongo.db[APPROVALS].find_one(
            {"_id": approval_id, "owner_id": ctx.owner_id}
        )
        latest = await self._operations.get_by_key(ctx.owner_id, "order_create", idempotency_key)
        if latest:
            if latest.get("payload_hash") != payload_hash:
                raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "idempotency key payload differs", http_status=409)
            if latest.get("status") == "succeeded":
                return latest["result"]
        if draft_before_claim is None:
            raise AppError(ErrorCodes.NOT_FOUND, "draft not found", http_status=404)
        draft_doc = await self._mongo.db["drafts"].find_one(
            {"_id": draft_id, "owner_id": ctx.owner_id}, {"workflow_run_id": 1}
        )
        workflow_run_id = (draft_doc or {}).get("workflow_run_id")
        if workflow_run_id and ctx.run_id != workflow_run_id:
            raise AppError(ErrorCodes.APPROVAL_REQUIRED,
                           "workflow-owned orders must be committed through their owning run", http_status=403)
        if approval_before_claim is None:
            raise AppError(ErrorCodes.APPROVAL_REQUIRED, "an approved decision is required", http_status=403)
        if (approval_before_claim.get("status") != "pending"
                or approval_before_claim.get("decision") != "approve"
                or approval_before_claim.get("draft_id") != draft_before_claim.id):
            raise AppError(ErrorCodes.APPROVAL_REQUIRED, "approval is not approved for this draft", http_status=403)
        if (approval_before_claim.get("draft_version") != draft_before_claim.version
                or approval_before_claim.get("payload_hash") != draft_hash(draft_before_claim)
                or draft_before_claim.state != "pending_approval"):
            raise AppError(ErrorCodes.STALE_APPROVAL, "approval is superseded", http_status=409)
        for item in draft_before_claim.items:
            part = await self._mongo.db[PARTS].find_one({"_id": item.part_id})
            if part is None or part.get("active", True) is not True:
                raise AppError(ErrorCodes.VALIDATION_ERROR,
                               "part is missing or inactive", http_status=409)
        await self._supersede_changed_snapshot(draft_before_claim, approval_id, ctx, now)

        operation, claimed = await self._operations.claim(
            ctx.owner_id, "order_create", idempotency_key, payload_hash, now,
            run_id=ctx.run_id)
        if operation["payload_hash"] != payload_hash:
            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "idempotency key payload differs", http_status=409)
        if operation["status"] == "succeeded":
            return operation["result"]
        if not claimed:
            if operation["status"] in {"processing", "outcome_unknown"}:
                for _ in range(75):
                    await asyncio.sleep(0.2)
                    current = await self._operations.get_by_key(
                        ctx.owner_id, "order_create", idempotency_key
                    )
                    if current and current.get("payload_hash") != payload_hash:
                        raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "idempotency key payload differs", http_status=409)
                    if current and current.get("status") == "succeeded":
                        return current["result"]
                    if current and current.get("lease_expires_at") and current["lease_expires_at"] <= self._clock.now():
                        return await self.execute(draft_id, approval_id, idempotency_key, ctx)
            raise AppError(ErrorCodes.DEPENDENCY_UNAVAILABLE,
                           "operation is processing; reconcile before retry", http_status=202, retryable=True,
                           data={"operation_id": operation["_id"], "status": operation["status"]})
        self._fault("after_claim")
        result_payload: dict | None = None

        async def apply(session):
            nonlocal result_payload
            await self._operations.assert_lease(
                operation["_id"], operation["lease_owner"], self._clock.now(), session=session
            )
            existing = await self._operations.get_by_key(ctx.owner_id, "order_create", idempotency_key, session)
            if existing and existing.get("status") == "succeeded":
                result_payload = existing["result"]
                return
            draft = await self._drafts.get(ctx.owner_id, draft_id, session=session)
            approval = await self._mongo.db[APPROVALS].find_one(
                {"_id": approval_id, "owner_id": ctx.owner_id}, session=session)
            if draft is None:
                raise AppError(ErrorCodes.NOT_FOUND, "draft not found", http_status=404)
            if approval is None:
                raise AppError(ErrorCodes.APPROVAL_REQUIRED, "an approved decision is required", http_status=403)
            if approval.get("status") != "pending" or approval.get("decision") != "approve" or approval.get("draft_id") != draft.id:
                raise AppError(ErrorCodes.APPROVAL_REQUIRED, "approval is not approved for this draft", http_status=403)
            if approval.get("draft_version") != draft.version or approval.get("payload_hash") != draft_hash(draft):
                raise AppError(ErrorCodes.STALE_APPROVAL, "approval is superseded", http_status=409)
            if draft.state != "pending_approval":
                raise AppError(ErrorCodes.STALE_APPROVAL, "draft is not pending approval", http_status=409)

            inventory_deltas: dict[str, int] = {}
            inventory_versions: dict[str, int] = {}
            for item in draft.items:
                part = await self._mongo.db[PARTS].find_one({"_id": item.part_id}, session=session)
                if part is None or part.get("active", True) is not True:
                    raise AppError(ErrorCodes.VALIDATION_ERROR,
                                   "part is missing or inactive", http_status=409)
                quote_doc = await self._mongo.db[QUOTES].find_one({"_id": item.quote_id}, session=session)
                if quote_doc is None:
                    raise AppError(ErrorCodes.VALIDATION_ERROR, "quote is no longer available", http_status=409)
                quote_doc["id"] = quote_doc.pop("_id")
                quote = Quote(**quote_doc)
                if (quote.part_id != item.part_id or quote.supplier_id != draft.supplier_id
                        or quote.unit_price_cents != item.unit_price_cents or quote.valid_until <= now
                        or quote.min_order_qty > item.quantity
                        or draft.quote_snapshots.get(quote.id) != quote_snapshot(quote)):
                    raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "quote changed; a new confirmation is required", http_status=409)
                supplier_doc = await self._mongo.db[SUPPLIERS].find_one({"_id": quote.supplier_id}, session=session)
                if supplier_doc is None:
                    raise AppError(ErrorCodes.VALIDATION_ERROR, "supplier not found", http_status=422)
                supplier_doc["id"] = supplier_doc.pop("_id")
                if Supplier(**supplier_doc).status != "active":
                    raise AppError(ErrorCodes.VALIDATION_ERROR, "supplier is inactive", http_status=409)
                inv = await self._mongo.db[INVENTORIES].find_one(
                    {"part_id": item.part_id, "warehouse_id": draft.warehouse_id}, session=session)
                if inv is None:
                    raise AppError(ErrorCodes.NOT_FOUND, "inventory not found", http_status=404)
                inv["id"] = inv.pop("_id")
                inventory = Inventory(**inv)
                expected = draft.snapshot_versions.get(inventory.id)
                if expected is not None and inventory.version != expected:
                    raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "inventory changed; a new confirmation is required", http_status=409)
                inventory_deltas[inventory.id] = inventory_deltas.get(inventory.id, 0) + item.quantity
                inventory_versions[inventory.id] = inventory.version
            if ctx.run_id:
                fenced = await self._mongo.db[RUNS].update_one(
                    {"_id": ctx.run_id, "owner_id": ctx.owner_id, "status": "running",
                     "cancel_requested": False},
                    {"$inc": {"commit_fence": 1}}, session=session,
                )
                if fenced.modified_count != 1:
                    raise AppError(ErrorCodes.RUN_NOT_ACTIVE,
                                   "run cancellation prevents order commit", http_status=409)
            order = await self._orders.create_from_draft(draft, operation["_id"], now, session=session)
            self._fault("after_order_write")
            for inventory_id, quantity in inventory_deltas.items():
                if not await self._inventory.adjust_inbound(
                    inventory_id, quantity, inventory_versions[inventory_id], session=session
                ):
                    raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "inventory changed during approval", http_status=409)
            await self._mongo.db[APPROVALS].update_one(
                {"_id": approval_id, "owner_id": ctx.owner_id, "status": "pending", "decision": "approve"},
                {"$set": {"status": "consumed", "order_id": order.id, "updated_at": now}}, session=session)
            await self._mongo.db["drafts"].update_one(
                {"_id": draft.id, "owner_id": ctx.owner_id, "version": draft.version,
                 "state": "pending_approval"}, {"$set": {"state": "approved", "updated_at": now}}, session=session)
            result_payload = {"operation_id": operation["_id"], "status": "succeeded",
                              "order": order.model_dump(mode="json")}
            await self._operations.mark_succeeded(
                operation["_id"], operation["lease_owner"], result_payload,
                order.id, self._clock.now(), session=session,
            )

        try:
            attempts = 0
            while True:
                attempts += 1
                try:
                    async with self._mongo.transaction() as session:
                        await apply(session)
                    break
                except OperationFailure as exc:
                    if exc.has_error_label("TransientTransactionError") and attempts < 5:
                        continue
                    raise
        except AppError as exc:
            if exc.code == ErrorCodes.RUN_NOT_ACTIVE:
                await self._operations.mark_failed(
                    operation["_id"], operation["lease_owner"], exc.code, self._clock.now()
                )
            raise
        except Exception:
            # Keep the lease record for reconciliation/retry; the transaction has no partial writes.
            raise
        self._fault("after_commit_before_response")
        return result_payload or {}
