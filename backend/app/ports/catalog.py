"""CatalogReader：P01 只读业务目录端口。"""

from __future__ import annotations

from typing import Protocol

from backend.app.contracts.common import Page, PageQuery
from backend.app.contracts.domain import Part, Quote, Supplier


class CatalogReader(Protocol):
    async def search_parts(self, name: str | None, page: PageQuery) -> Page[Part]: ...

    async def get_part(self, part_id: str) -> Part: ...

    async def list_parts(self, part_ids: list[str]) -> list[Part]: ...

    async def search_suppliers(self, name: str | None, page: PageQuery) -> Page[Supplier]: ...

    async def get_supplier(self, supplier_id: str) -> Supplier: ...

    async def list_suppliers(self, supplier_ids: list[str]) -> list[Supplier]: ...

    async def list_quotes(self, part_ids: list[str]) -> list[Quote]: ...

    async def page_quotes(
        self,
        part_name: str | None,
        part_id: str | None,
        supplier_id: str | None,
        page: PageQuery,
    ) -> Page[Quote]: ...
