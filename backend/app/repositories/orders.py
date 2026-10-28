"""P04 采购订单只读仓储。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from backend.app.contracts.common import Page, PageQuery, make_page
from backend.app.contracts.domain import OrderDraft, PurchaseOrder, PurchaseOrderItem
from backend.app.repositories.indexes import ORDERS
from backend.app.repositories.mongo import MongoResources
from pymongo.asynchronous.client_session import AsyncClientSession


class OrderRepository:
    def __init__(self, mongo: MongoResources) -> None:
        self._mongo = mongo

    async def create_from_draft(
        self, draft: OrderDraft, operation_id: str, now: datetime, *, session: AsyncClientSession,
        verification_facts: dict[str, Any] | None = None,
    ) -> PurchaseOrder:
        order_id = f"po_{uuid4().hex}"
        order = PurchaseOrder(
            id=order_id, number="PO-" + operation_id[-10:].upper(), owner_id=draft.owner_id,
            draft_id=draft.id, supplier_id=draft.supplier_id, warehouse_id=draft.warehouse_id,
            items=[PurchaseOrderItem(**item.model_dump(), received_qty=0) for item in draft.items],
            total_cents=draft.total_cents, status="submitted", version=1, created_at=now,
        )
        payload = order.model_dump(mode="python", exclude={"id"})
        payload["operation_id"] = operation_id
        if verification_facts is not None:
            payload["verification_facts"] = verification_facts
        await self._mongo.db[ORDERS].insert_one({"_id": order.id, **payload}, session=session)
        return order

    async def page(self, owner_id: str, query: PageQuery) -> Page[PurchaseOrder]:
        collection = self._mongo.db[ORDERS]
        filter_ = {"owner_id": owner_id}
        total = await collection.count_documents(filter_)
        cursor = (collection.find(filter_).sort([("created_at", -1), ("_id", -1)])
                  .skip((query.page - 1) * query.page_size).limit(query.page_size))
        records = []
        async for doc in cursor:
            doc.pop("operation_id", None)
            doc.pop("verification_facts", None)
            doc["id"] = doc.pop("_id")
            records.append(PurchaseOrder(**doc))
        return make_page(records, total, query.page, query.page_size)

    async def get(self, owner_id: str, order_id: str) -> PurchaseOrder | None:
        doc = await self._mongo.db[ORDERS].find_one({"owner_id": owner_id, "_id": order_id})
        if doc is None:
            return None
        doc.pop("operation_id", None)
        doc.pop("verification_facts", None)
        doc["id"] = doc.pop("_id")
        return PurchaseOrder(**doc)

    async def get_by_operation(self, owner_id: str, operation_id: str) -> PurchaseOrder | None:
        doc = await self._mongo.db[ORDERS].find_one(
            {"owner_id": owner_id, "operation_id": operation_id}
        )
        if doc is None:
            return None
        doc.pop("operation_id", None)
        doc.pop("verification_facts", None)
        doc["id"] = doc.pop("_id")
        return PurchaseOrder(**doc)

    async def search_details(self, owner_id: str, *, status: str | None = None,
                             supplier_id: str | None = None, part_id: str | None = None,
                             query: PageQuery) -> Page[PurchaseOrder]:
        filter_: dict[str, Any] = {"owner_id": owner_id}
        if status:
            if status not in {"submitted", "shipped", "received", "completed", "cancelled"}:
                from backend.app.contracts.common import AppError, ErrorCodes
                raise AppError(ErrorCodes.VALIDATION_ERROR, "unknown order status", 422)
            filter_["status"] = status
        if supplier_id:
            filter_["supplier_id"] = supplier_id
        if part_id:
            filter_["items.part_id"] = part_id
        collection = self._mongo.db[ORDERS]
        total = await collection.count_documents(filter_)
        cursor = (collection.find(filter_).sort([("created_at", -1), ("_id", -1)])
                  .skip((query.page - 1) * query.page_size).limit(query.page_size))
        records = []
        async for doc in cursor:
            doc.pop("operation_id", None)
            doc.pop("verification_facts", None)
            doc["id"] = doc.pop("_id")
            records.append(PurchaseOrder(**doc))
        return make_page(records, total, query.page, query.page_size)
