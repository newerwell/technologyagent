"""P08 approved stock movement and receipt transactions."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable
from uuid import uuid4

from backend.app.contracts.common import AppError, Clock, ErrorCodes, RequestContext
from backend.app.repositories.indexes import APPROVALS, INVENTORIES, MOVEMENTS, OPERATIONS, ORDERS, RECEIPTS
from backend.app.repositories.mongo import MongoResources
from backend.app.repositories.operations import OperationRepository
from backend.app.repositories.movements import MovementRepository

FaultHook = Callable[[str], None]


def canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class InventoryMutationService:
    """All stock facts and receipt/operation/approval records commit together."""

    def __init__(self, mongo: MongoResources, clock: Clock, fault_hook: FaultHook | None = None) -> None:
        self.mongo, self.clock, self.fault_hook = mongo, clock, fault_hook
        self.operations = OperationRepository(mongo)
        self.movements = MovementRepository(mongo)

    def _fault(self, point: str) -> None:
        if self.fault_hook:
            self.fault_hook(point)

    async def receive(self, *, order_id: str, receipt_id: str, warehouse_id: str,
                      items: list[dict[str, Any]], approval_id: str, idempotency_key: str,
                      ctx: RequestContext, provider: str = "local_seed") -> dict[str, Any]:
        merged: dict[str, int] = {}
        for item in items:
            part_id, quantity = item.get("part_id"), item.get("quantity")
            if not isinstance(part_id, str) or not part_id or type(quantity) is not int or quantity < 1:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "receipt item requires part_id and positive integer quantity", 422)
            merged[part_id] = merged.get(part_id, 0) + quantity
        if not merged:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "receipt items are required", 422)
        canonical_items = [{"part_id": key, "quantity": merged[key]} for key in sorted(merged)]
        payload = {"order_id": order_id, "receipt_id": receipt_id, "warehouse_id": warehouse_id, "items": canonical_items}
        digest = canonical_hash(payload)
        previous = await self.movements.receipt(ctx.owner_id, provider, receipt_id)
        if previous:
            if previous["payload_hash"] != digest:
                raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "receipt id already used with different facts", 409)
            return previous["result"]
        approval = await self.mongo.db[APPROVALS].find_one({"_id": approval_id, "owner_id": ctx.owner_id})
        if (approval is None or approval.get("decision") != "approve" or approval.get("status") != "pending"
                or approval.get("action") != "inventory_receive" or approval.get("payload_hash") != digest):
            raise AppError(ErrorCodes.APPROVAL_REQUIRED, "approved receipt proposal matching this payload is required", 403)
        now = self.clock.now()
        op, claimed = await self.operations.claim(ctx.owner_id, "inventory_receive", idempotency_key, digest, now, run_id=ctx.run_id)
        if op.get("payload_hash") != digest:
            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "idempotency key payload differs", 409)
        if op.get("status") == "succeeded":
            return op["result"]
        if not claimed:
            raise AppError(ErrorCodes.OUTCOME_UNKNOWN, "operation is processing; reconcile before retry", 409, retryable=True,
                           data={"operation_id": op["_id"], "status": op["status"]})
        self._fault("after_claim")
        result: dict[str, Any] = {}
        async with self.mongo.transaction() as session:
            await self.operations.assert_lease(op["_id"], op["lease_owner"], now, session=session)
            duplicate = await self.movements.receipt(ctx.owner_id, provider, receipt_id, session=session)
            if duplicate:
                if duplicate["payload_hash"] != digest:
                    raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "receipt id conflicts", 409)
                result.update(duplicate["result"])
            else:
                current_approval = await self.mongo.db[APPROVALS].find_one(
                    {"_id": approval_id, "owner_id": ctx.owner_id, "status": "pending", "decision": "approve",
                     "action": "inventory_receive", "payload_hash": digest}, session=session)
                if current_approval is None:
                    raise AppError(ErrorCodes.APPROVAL_REQUIRED, "receipt approval is no longer valid", 403)
                order = await self.mongo.db[ORDERS].find_one({"_id": order_id, "owner_id": ctx.owner_id}, session=session)
                if order is None or order.get("warehouse_id") != warehouse_id or order.get("status") not in {"shipped", "submitted"}:
                    raise AppError(ErrorCodes.VALIDATION_ERROR, "order is missing, wrong-warehouse, or not receivable", 409)
                order_lines = {line["part_id"]: line for line in order["items"]}
                receipt_result = {"receipt_id": receipt_id, "order_id": order_id, "items": canonical_items,
                                  "status": "received", "operation_id": op["_id"]}
                self._fault("before_receipt_write")
                await self.mongo.db[RECEIPTS].insert_one({"_id": "rcpt_" + uuid4().hex, "owner_id": ctx.owner_id,
                    "provider": provider, "receipt_id": receipt_id, "order_id": order_id, "warehouse_id": warehouse_id,
                    "items": canonical_items, "operation_id": op["_id"], "payload_hash": digest,
                    "result": receipt_result, "created_at": now}, session=session)
                for index, line in enumerate(canonical_items):
                    order_line = order_lines.get(line["part_id"])
                    quantity = line["quantity"]
                    if order_line is None or order_line["quantity"] - order_line.get("received_qty", 0) < quantity:
                        raise AppError(ErrorCodes.VALIDATION_ERROR, "receipt exceeds remaining ordered quantity", 409)
                    inventory = await self.mongo.db[INVENTORIES].find_one(
                        {"part_id": line["part_id"], "warehouse_id": warehouse_id}, session=session)
                    if inventory is None or inventory.get("inbound", 0) < quantity:
                        raise AppError(ErrorCodes.VALIDATION_ERROR, "inventory inbound is insufficient for receipt", 409)
                    result_update = await self.mongo.db[INVENTORIES].update_one(
                        {"_id": inventory["_id"], "version": inventory["version"], "inbound": {"$gte": quantity}},
                        {"$inc": {"on_hand": quantity, "inbound": -quantity, "version": 1}}, session=session)
                    if result_update.modified_count != 1:
                        raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "inventory changed during receipt", 409)
                    order_line["received_qty"] = order_line.get("received_qty", 0) + quantity
                    self._fault("after_inventory_write")
                    await self.mongo.db[MOVEMENTS].insert_one({"_id": "mov_" + uuid4().hex, "owner_id": ctx.owner_id,
                        "provider": provider, "inventory_id": inventory["_id"], "operation_id": op["_id"],
                        "line_index": index, "receipt_id": receipt_id, "order_id": order_id,
                        "part_id": line["part_id"], "warehouse_id": warehouse_id,
                        "on_hand_delta": quantity, "inbound_delta": -quantity, "reserved_delta": 0, "created_at": now}, session=session)
                    self._fault("after_movement_write")
                complete = all(line.get("received_qty", 0) == line["quantity"] for line in order["items"])
                await self.mongo.db[ORDERS].update_one({"_id": order_id, "owner_id": ctx.owner_id, "version": order["version"]},
                    {"$set": {"items": order["items"], "status": "received" if complete else "shipped"}, "$inc": {"version": 1}}, session=session)
                await self.mongo.db[APPROVALS].update_one({"_id": approval_id, "owner_id": ctx.owner_id, "status": "pending"},
                    {"$set": {"status": "consumed", "operation_id": op["_id"], "updated_at": now}}, session=session)
                self._fault("before_operation_success")
                await self.operations.mark_succeeded(op["_id"], op["lease_owner"], receipt_result, order_id, now, session=session)
                result.update(receipt_result)
        self._fault("after_commit_before_response")
        return result
