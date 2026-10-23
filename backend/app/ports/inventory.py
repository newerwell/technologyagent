"""InventoryReader：P01 只读库存端口。"""

from __future__ import annotations

from typing import Protocol

from backend.app.contracts.common import Page
from backend.app.contracts.domain import Inventory, InventoryQuery


class InventoryReader(Protocol):
    async def page(self, query: InventoryQuery) -> Page[Inventory]: ...

    async def get(self, inventory_id: str) -> Inventory: ...

    async def list_scope(self, part_ids: list[str], warehouse_id: str) -> list[Inventory]: ...

    async def list_all(
        self, warehouse_id: str | None = None, part_name: str | None = None
    ) -> list[Inventory]: ...
