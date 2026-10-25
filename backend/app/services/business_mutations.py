"""P08 generic approved business proposal executor for non-order-create actions."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from backend.app.contracts.common import AppError, Clock, ErrorCodes, RequestContext
from backend.app.contracts.domain import PurchaseOrderItem, Quote
from backend.app.repositories.indexes import APPROVALS, INVENTORIES, MOVEMENTS, OPERATIONS, ORDERS, PARTS, SUPPLIERS
from backend.app.repositories.mongo import MongoResources
from backend.app.repositories.operations import OperationRepository
from backend.app.services.inventory import canonical_hash


class BusinessMutationService:
    ALLOWED = {"supplier_create", "supplier_update_status", "part_create", "inventory_inbound",
               "inventory_outbound", "order_update_status", "order_update"}

    def __init__(self, mongo: MongoResources, clock: Clock) -> None:
        self.mongo, self.clock = mongo, clock
        self.operations = OperationRepository(mongo)

    async def execute(self, approval_id: str, idempotency_key: str, ctx: RequestContext,
                      *, expected_action: str | None = None) -> dict[str, Any]:
        approval = await self.mongo.db[APPROVALS].find_one({"_id": approval_id, "owner_id": ctx.owner_id})
        if not approval or "proposal_payload" not in approval or approval.get("action") not in self.ALLOWED:
            raise AppError(ErrorCodes.NOT_FOUND, "business proposal not found", 404)
        if expected_action and approval.get("action") != expected_action:
            raise AppError(ErrorCodes.APPROVAL_REQUIRED, "approval is bound to a different action", 403)
        payload, action = approval["proposal_payload"], approval["action"]
        digest = canonical_hash({"approval_id": approval_id, "action": action, "payload": payload})
        existing = await self.operations.get_by_key(ctx.owner_id, action, idempotency_key)
        if existing and existing.get("payload_hash") != digest:
            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "idempotency key payload differs", 409)
        if existing and existing.get("status") == "succeeded":
            return existing["result"]
        if approval.get("decision") != "approve" or approval.get("status") != "pending":
            raise AppError(ErrorCodes.APPROVAL_REQUIRED, "proposal must be approved before execution", 403)
        now = self.clock.now()
        op, claimed = await self.operations.claim(ctx.owner_id, action, idempotency_key, digest, now, run_id=ctx.run_id)
        if op.get("payload_hash") != digest:
            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "idempotency key payload differs", 409)
        if op.get("status") == "succeeded":
            return op["result"]
        if not claimed:
            raise AppError(ErrorCodes.OUTCOME_UNKNOWN, "operation is processing; reconcile before retry", 409, retryable=True)
        result: dict[str, Any] = {}
        try:
            async with self.mongo.transaction() as session:
                await self.operations.assert_lease(op["_id"], op["lease_owner"], now, session=session)
                current = await self.mongo.db[APPROVALS].find_one({"_id": approval_id, "owner_id": ctx.owner_id,
                    "status": "pending", "decision": "approve", "payload_hash": approval["payload_hash"]}, session=session)
                if current is None:
                    raise AppError(ErrorCodes.APPROVAL_REQUIRED, "approval became stale", 409)
                result = await self._apply(action, payload, op["_id"], ctx, now, session)
                await self.mongo.db[APPROVALS].update_one({"_id": approval_id, "owner_id": ctx.owner_id, "status": "pending"},
                    {"$set": {"status": "consumed", "operation_id": op["_id"], "updated_at": now}}, session=session)
                await self.operations.mark_succeeded(op["_id"], op["lease_owner"], result,
                    str(result.get("id", "")), now, session=session)
        except AppError as exc:
            await self.operations.mark_failed(op["_id"], op["lease_owner"], exc.code, self.clock.now())
            raise
        return result

    async def _apply(self, action: str, payload: dict[str, Any], operation_id: str,
                     ctx: RequestContext, now: datetime, session) -> dict[str, Any]:
        db = self.mongo.db
        if action == "supplier_create":
            if not payload.get("code") or not payload.get("name"):
                raise AppError(ErrorCodes.VALIDATION_ERROR, "supplier code and name are required", 422)
            duplicate = await db[SUPPLIERS].find_one({"code": payload["code"]}, session=session)
            if duplicate:
                raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "supplier code already exists", 409)
            doc = {"_id": "sup_" + uuid4().hex, "code": payload["code"], "name": payload["name"],
                   "status": "active", "credit_rating": payload.get("credit_rating"), "schema_version": 1}
            await db[SUPPLIERS].insert_one(doc, session=session)
            return {"id": doc["_id"], "code": doc["code"], "name": doc["name"], "status": doc["status"]}
        if action == "supplier_update_status":
            if payload.get("status") not in {"active", "inactive"}:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "invalid supplier status", 422)
            updated = await db[SUPPLIERS].update_one({"_id": payload.get("supplier_id")},
                {"$set": {"status": payload["status"]}}, session=session)
            if updated.modified_count != 1:
                raise AppError(ErrorCodes.NOT_FOUND, "supplier not found or unchanged", 404)
            return {"supplier_id": payload["supplier_id"], "status": payload["status"]}
        if action == "part_create":
            required = ("code", "name", "unit")
            if any(not isinstance(payload.get(key), str) or not payload[key].strip() for key in required):
                raise AppError(ErrorCodes.VALIDATION_ERROR, "part code, name, and unit are required", 422)
            duplicate = await db[PARTS].find_one({"code": payload["code"]}, session=session)
            if duplicate:
                raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "part code already exists", 409)
            doc = {"_id": "part_" + uuid4().hex, "code": payload["code"], "name": payload["name"],
                   "unit": payload["unit"], "specification": payload.get("specification", ""),
                   "category": payload.get("category", ""), "active": True, "schema_version": 1}
            await db[PARTS].insert_one(doc, session=session)
            return {"id": doc["_id"], "code": doc["code"], "name": doc["name"], "unit": doc["unit"], "active": True}
        if action in {"inventory_inbound", "inventory_outbound"}:
            quantity = payload.get("quantity")
            if type(quantity) is not int or quantity <= 0:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "quantity must be a positive integer", 422)
            inv = await db[INVENTORIES].find_one({"_id": payload.get("inventory_id")}, session=session)
            if inv is None:
                raise AppError(ErrorCodes.NOT_FOUND, "inventory not found", 404)
            expected_version = payload.get("expected_version")
            if type(expected_version) is not int or expected_version != inv["version"]:
                raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "inventory version is stale", 409)
            is_inbound = action == "inventory_inbound"
            if not is_inbound and inv["on_hand"] - quantity < inv["reserved"]:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "outbound cannot reduce stock below reserved", 409)
            delta = quantity if is_inbound else -quantity
            await db[INVENTORIES].update_one({"_id": inv["_id"], "version": inv["version"]},
                {"$inc": {"on_hand": delta, "version": 1}}, session=session)
            await db[MOVEMENTS].insert_one({"_id": "mov_" + uuid4().hex, "owner_id": ctx.owner_id,
                "provider": "local_seed", "inventory_id": inv["_id"], "operation_id": operation_id,
                "line_index": 0, "part_id": inv["part_id"], "warehouse_id": inv["warehouse_id"],
                "on_hand_delta": delta, "inbound_delta": 0, "reserved_delta": 0, "created_at": now}, session=session)
            return {"inventory_id": inv["_id"], "on_hand": inv["on_hand"] + delta,
                    "inbound": inv["inbound"], "version": inv["version"] + 1}
        if action == "order_update_status":
            target = payload.get("status")
            order = await db[ORDERS].find_one({"_id": payload.get("order_id"), "owner_id": ctx.owner_id}, session=session)
            if order is None:
                raise AppError(ErrorCodes.NOT_FOUND, "order not found", 404)
            if type(payload.get("expected_version")) is not int or payload["expected_version"] != order["version"]:
                raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "order version is stale", 409)
            valid = {"submitted": {"shipped", "cancelled"}, "shipped": {"received"}, "received": {"completed"}}
            if target not in valid.get(order["status"], set()):
                raise AppError(ErrorCodes.VALIDATION_ERROR, "invalid order status transition", 409)
            if target == "received" and any(line.get("received_qty", 0) != line["quantity"] for line in order["items"]):
                raise AppError(ErrorCodes.VALIDATION_ERROR, "cannot mark order received before all receipts", 409)
            if target == "cancelled":
                for line in order["items"]:
                    remaining = line["quantity"] - line.get("received_qty", 0)
                    if remaining:
                        inv = await db[INVENTORIES].find_one({"part_id": line["part_id"], "warehouse_id": order["warehouse_id"]}, session=session)
                        if inv is None or inv["inbound"] < remaining:
                            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "inbound does not reconcile with order cancellation", 409)
                        await db[INVENTORIES].update_one({"_id": inv["_id"], "version": inv["version"]},
                            {"$inc": {"inbound": -remaining, "version": 1}}, session=session)
            await db[ORDERS].update_one({"_id": order["_id"], "version": order["version"]},
                {"$set": {"status": target}, "$inc": {"version": 1}}, session=session)
            return {"id": order["_id"], "status": target, "version": order["version"] + 1}
        if action == "order_update":
            order = await db[ORDERS].find_one({"_id": payload.get("order_id"), "owner_id": ctx.owner_id}, session=session)
            if order is None:
                raise AppError(ErrorCodes.NOT_FOUND, "order not found", 404)
            if order.get("status") != "submitted":
                raise AppError(ErrorCodes.VALIDATION_ERROR, "only submitted orders can be amended", 409)
            if type(payload.get("expected_version")) is not int or payload["expected_version"] != order["version"]:
                raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "order version is stale", 409)
            changes = payload.get("items")
            if not isinstance(changes, list) or not changes:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "order amendment items are required", 422)
            old_quantities = {line["part_id"]: line["quantity"] - line.get("received_qty", 0) for line in order["items"]}
            new_lines: list[PurchaseOrderItem] = []
            seen: set[str] = set()
            for item in changes:
                part_id, quantity, quote_id = item.get("part_id"), item.get("quantity"), item.get("quote_id")
                if not isinstance(part_id, str) or not part_id or part_id in seen or type(quantity) is not int or quantity < 1:
                    raise AppError(ErrorCodes.VALIDATION_ERROR, "amendment requires unique parts and positive integer quantities", 422)
                seen.add(part_id)
                part = await db[PARTS].find_one({"_id": part_id}, session=session)
                quote_doc = await db["quotes"].find_one({"_id": quote_id}, session=session)
                if part is None or part.get("active", True) is not True or quote_doc is None:
                    raise AppError(ErrorCodes.VALIDATION_ERROR, "amendment part/quote is missing or inactive", 409)
                quote_values = dict(quote_doc)
                quote_values["id"] = quote_values.pop("_id")
                quote = Quote(**quote_values)
                supplier = await db[SUPPLIERS].find_one({"_id": quote.supplier_id}, session=session)
                if (quote.part_id != part_id or quote.supplier_id != order["supplier_id"] or supplier is None
                        or supplier.get("status") != "active" or quote.valid_until <= now or quote.min_order_qty > quantity):
                    raise AppError(ErrorCodes.VALIDATION_ERROR, "amendment quote is invalid for this supplier or quantity", 409)
                line_total = quote.unit_price_cents * quantity
                new_lines.append(PurchaseOrderItem(part_id=part_id, quantity=quantity,
                    unit_price_cents=quote.unit_price_cents, quote_id=quote.id,
                    line_total_cents=line_total, received_qty=0))
            new_quantities = {line.part_id: line.quantity - line.received_qty for line in new_lines}
            for part_id in set(old_quantities) | set(new_quantities):
                delta = new_quantities.get(part_id, 0) - old_quantities.get(part_id, 0)
                if delta == 0:
                    continue
                inv = await db[INVENTORIES].find_one({"part_id": part_id, "warehouse_id": order["warehouse_id"]}, session=session)
                if inv is None or inv["inbound"] + delta < 0:
                    raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "inbound cannot reconcile with the amendment", 409)
                updated = await db[INVENTORIES].update_one({"_id": inv["_id"], "version": inv["version"]},
                    {"$inc": {"inbound": delta, "version": 1}}, session=session)
                if updated.modified_count != 1:
                    raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "inventory changed during amendment", 409)
            total_cents = sum(line.line_total_cents for line in new_lines)
            updated = await db[ORDERS].update_one({"_id": order["_id"], "owner_id": ctx.owner_id,
                "version": order["version"], "status": "submitted"},
                {"$set": {"items": [line.model_dump(mode="python") for line in new_lines],
                           "total_cents": total_cents}, "$inc": {"version": 1}}, session=session)
            if updated.modified_count != 1:
                raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "order changed during amendment", 409)
            return {"id": order["_id"], "number": order["number"], "status": "submitted",
                    "version": order["version"] + 1, "total_cents": total_cents,
                    "items": [line.model_dump(mode="json") for line in new_lines]}
        raise AppError(ErrorCodes.UNSUPPORTED_OPERATION, f"unsupported business mutation: {action}", 405)
