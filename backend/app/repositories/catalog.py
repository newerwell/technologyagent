"""MongoDB 目录仓储：零件、供应商、报价的分页与批量读取。"""

from __future__ import annotations

import re
from typing import Any

from backend.app.contracts.common import ErrorCodes, AppError, Page, PageQuery, make_page
from backend.app.contracts.domain import Part, Quote, Supplier
from backend.app.repositories.indexes import PARTS, QUOTES, SUPPLIERS
from backend.app.repositories.mongo import MongoResources


def _regex(name: str) -> dict[str, str]:
    return {"$regex": re.escape(name), "$options": "i"}


def _to_model(model, document: dict[str, Any]):
    payload = dict(document)
    payload["id"] = payload.pop("_id")
    return model(**payload)


class CatalogRepository:
    def __init__(self, mongo: MongoResources) -> None:
        self._mongo = mongo

    async def search_parts(self, name: str | None, page: PageQuery) -> Page[Part]:
        query = {"name": _regex(name)} if name else {}
        collection = self._mongo.db[PARTS]
        total = await collection.count_documents(query)
        cursor = (
            collection.find(query)
            .sort("_id", 1)
            .skip((page.page - 1) * page.page_size)
            .limit(page.page_size)
        )
        records = [_to_model(Part, doc) async for doc in cursor]
        return make_page(records, total, page.page, page.page_size)

    async def get_part(self, part_id: str) -> Part:
        doc = await self._mongo.db[PARTS].find_one({"_id": part_id})
        if doc is None:
            raise AppError(ErrorCodes.NOT_FOUND, f"part not found: {part_id}", http_status=404)
        return _to_model(Part, doc)

    async def list_parts(self, part_ids: list[str]) -> list[Part]:
        if not part_ids:
            return []
        cursor = self._mongo.db[PARTS].find({"_id": {"$in": part_ids}}).sort("_id", 1)
        return [_to_model(Part, doc) async for doc in cursor]

    async def search_suppliers(self, name: str | None, page: PageQuery) -> Page[Supplier]:
        query = {"name": _regex(name)} if name else {}
        collection = self._mongo.db[SUPPLIERS]
        total = await collection.count_documents(query)
        cursor = (
            collection.find(query)
            .sort("_id", 1)
            .skip((page.page - 1) * page.page_size)
            .limit(page.page_size)
        )
        records = [_to_model(Supplier, doc) async for doc in cursor]
        return make_page(records, total, page.page, page.page_size)

    async def get_supplier(self, supplier_id: str) -> Supplier:
        doc = await self._mongo.db[SUPPLIERS].find_one({"_id": supplier_id})
        if doc is None:
            raise AppError(
                ErrorCodes.NOT_FOUND, f"supplier not found: {supplier_id}", http_status=404
            )
        return _to_model(Supplier, doc)

    async def list_suppliers(self, supplier_ids: list[str]) -> list[Supplier]:
        if not supplier_ids:
            return []
        cursor = self._mongo.db[SUPPLIERS].find({"_id": {"$in": supplier_ids}}).sort("_id", 1)
        return [_to_model(Supplier, doc) async for doc in cursor]

    async def list_quotes(self, part_ids: list[str]) -> list[Quote]:
        if not part_ids:
            return []
        cursor = self._mongo.db[QUOTES].find({"part_id": {"$in": part_ids}}).sort("_id", 1)
        return [_to_model(Quote, doc) async for doc in cursor]

    async def _matching_part_ids(self, name: str) -> list[str]:
        cursor = self._mongo.db[PARTS].find({"name": _regex(name)}, {"_id": 1})
        return [doc["_id"] async for doc in cursor]

    async def page_quotes(
        self,
        part_name: str | None,
        part_id: str | None,
        supplier_id: str | None,
        page: PageQuery,
    ) -> Page[Quote]:
        query: dict[str, Any] = {}
        if supplier_id:
            query["supplier_id"] = supplier_id
        if part_name:
            matching = await self._matching_part_ids(part_name)
            if not matching:
                return make_page([], 0, page.page, page.page_size)
            if part_id and part_id not in matching:
                return make_page([], 0, page.page, page.page_size)
            query["part_id"] = {"$in": [part_id] if part_id else matching}
        elif part_id:
            query["part_id"] = part_id

        collection = self._mongo.db[QUOTES]
        total = await collection.count_documents(query)
        cursor = (
            collection.find(query)
            .sort("_id", 1)
            .skip((page.page - 1) * page.page_size)
            .limit(page.page_size)
        )
        records = [_to_model(Quote, doc) async for doc in cursor]
        return make_page(records, total, page.page, page.page_size)
