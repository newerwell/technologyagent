"""MongoDB 库存仓储：筛选、分页、详情与范围读取。"""

from __future__ import annotations

import re
from typing import Any

from backend.app.contracts.common import AppError, ErrorCodes, Page, PageQuery, make_page
from backend.app.contracts.domain import Inventory, InventoryQuery
from backend.app.repositories.indexes import INVENTORIES, PARTS
from backend.app.repositories.mongo import MongoResources
from backend.app.domain.inventory import inbound_after_purchase
from pymongo.asynchronous.client_session import AsyncClientSession


def _regex(name: str) -> dict[str, str]:
    return {"$regex": re.escape(name), "$options": "i"}


def _to_model(document: dict[str, Any]) -> Inventory:
    payload = dict(document)
    payload["id"] = payload.pop("_id")
    return Inventory(**payload)


class InventoryRepository:
    def __init__(self, mongo: MongoResources) -> None:
        self._mongo = mongo

    async def _filter(
        self, warehouse_id: str | None, part_name: str | None
    ) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if warehouse_id:
            query["warehouse_id"] = warehouse_id
        if part_name:
            cursor = self._mongo.db[PARTS].find({"name": _regex(part_name)}, {"_id": 1})
            ids = [doc["_id"] async for doc in cursor]
            if not ids:
                query["part_id"] = {"$in": []}
            else:
                query["part_id"] = {"$in": ids}
        return query

    async def page(self, query: InventoryQuery) -> Page[Inventory]:
        mongo_filter = await self._filter(query.warehouse_id, query.part_name)
        collection = self._mongo.db[INVENTORIES]
        total = await collection.count_documents(mongo_filter)
        cursor = (
            collection.find(mongo_filter)
            .sort("_id", 1)
            .skip((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
        records = [_to_model(doc) async for doc in cursor]
        return make_page(records, total, query.page, query.page_size)

    async def get(self, inventory_id: str) -> Inventory:
        doc = await self._mongo.db[INVENTORIES].find_one({"_id": inventory_id})
        if doc is None:
            raise AppError(
                ErrorCodes.NOT_FOUND, f"inventory not found: {inventory_id}", http_status=404
            )
        return _to_model(doc)

    async def list_scope(self, part_ids: list[str], warehouse_id: str) -> list[Inventory]:
        if not part_ids:
            return []
        cursor = (
            self._mongo.db[INVENTORIES]
            .find({"part_id": {"$in": part_ids}, "warehouse_id": warehouse_id})
            .sort("_id", 1)
        )
        return [_to_model(doc) async for doc in cursor]

    async def list_all(
        self, warehouse_id: str | None = None, part_name: str | None = None
    ) -> list[Inventory]:
        mongo_filter = await self._filter(warehouse_id, part_name)
        cursor = self._mongo.db[INVENTORIES].find(mongo_filter).sort("_id", 1)
        return [_to_model(doc) async for doc in cursor]

    async def adjust_inbound(
        self, inventory_id: str, delta: int, expected_version: int,
        *, session: AsyncClientSession,
    ) -> bool:
        doc = await self._mongo.db[INVENTORIES].find_one({"_id": inventory_id}, session=session)
        if doc is None:
            return False
        inventory = _to_model(doc)
        if inventory.version != expected_version:
            return False
        inbound, version = inbound_after_purchase(inventory, delta)
        result = await self._mongo.db[INVENTORIES].update_one(
            {"_id": inventory_id, "version": expected_version},
            {"$set": {"inbound": inbound, "version": version}}, session=session,
        )
        return result.modified_count == 1
