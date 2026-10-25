"""目录/库存查询用例：仓储读取、来源包装与展示派生值。"""

from __future__ import annotations

from backend.app.contracts.common import Clock, Page, PageQuery, make_page
from backend.app.contracts.domain import (
    Inventory,
    InventoryQuery,
    InventorySummary,
    InventoryView,
    Part,
    Quote,
    QuoteView,
    Supplier,
)
from backend.app.domain.replenishment import stock_state, summarize_inventory
from backend.app.ports.catalog import CatalogReader
from backend.app.ports.inventory import InventoryReader


class CatalogService:
    def __init__(self, repository: CatalogReader, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    async def search_parts(self, name: str | None, page: PageQuery) -> Page[Part]:
        return await self._repository.search_parts(name, page)

    async def get_part(self, part_id: str) -> Part:
        return await self._repository.get_part(part_id)

    async def search_suppliers(self, name: str | None, page: PageQuery) -> Page[Supplier]:
        return await self._repository.search_suppliers(name, page)

    async def get_supplier(self, supplier_id: str) -> Supplier:
        return await self._repository.get_supplier(supplier_id)

    async def page_quotes(
        self,
        part_name: str | None,
        part_id: str | None,
        supplier_id: str | None,
        page: PageQuery,
    ) -> Page[QuoteView]:
        result = await self._repository.page_quotes(part_name, part_id, supplier_id, page)
        part_ids = {quote.part_id for quote in result.records}
        supplier_ids = {quote.supplier_id for quote in result.records}
        parts = {part.id: part for part in await self._repository.list_parts(list(part_ids))}
        suppliers = {
            supplier.id: supplier
            for supplier in await self._repository.list_suppliers(list(supplier_ids))
        }
        now = self._clock.now()
        views = []
        for quote in result.records:
            part = parts.get(quote.part_id)
            supplier = suppliers.get(quote.supplier_id)
            is_valid = bool(
                supplier
                and supplier.status == "active"
                and quote.valid_until > now
            )
            views.append(
                QuoteView(
                    **quote.model_dump(),
                    part_name=part.name if part else "未知物料",
                    part_unit=part.unit if part else "",
                    supplier_name=supplier.name if supplier else "未知供应商",
                    supplier_status=supplier.status if supplier else "inactive",
                    is_valid=is_valid,
                )
            )
        return make_page(views, result.total, result.page, result.page_size)


class InventoryService:
    def __init__(self, repository: InventoryReader, catalog: CatalogReader | None = None) -> None:
        self._repository = repository
        self._catalog = catalog

    def _view(self, inventory: Inventory, unit: str | None = None) -> InventoryView:
        state = stock_state(inventory)
        return InventoryView(
            **inventory.model_dump(),
            unit=unit,
            available=state.available,
            projected=state.projected,
            shortage=state.shortage,
            warning=state.warning,
        )

    async def page(self, query: InventoryQuery) -> Page[InventoryView]:
        result = await self._repository.page(query)
        units = await self._units(result.records)
        views = [self._view(inventory, units.get(inventory.part_id)) for inventory in result.records]
        return make_page(views, result.total, result.page, result.page_size)

    async def get(self, inventory_id: str) -> InventoryView:
        inventory = await self._repository.get(inventory_id)
        units = await self._units([inventory])
        return self._view(inventory, units.get(inventory.part_id))

    async def warnings(self, query: InventoryQuery) -> Page[InventoryView]:
        # 预警条件是派生值，必须基于全部匹配记录过滤后再分页。
        inventories = await self._repository.list_all(query.warehouse_id, query.part_name)
        units = await self._units(inventories)
        warnings = [self._view(inventory, units.get(inventory.part_id)) for inventory in inventories]
        warnings = [item for item in warnings if item.warning]
        total = len(warnings)
        start = (query.page - 1) * query.page_size
        records = warnings[start : start + query.page_size]
        return make_page(records, total, query.page, query.page_size)

    async def _units(self, inventories: list[Inventory]) -> dict[str, str]:
        if self._catalog is None:
            return {}
        part_ids = sorted({item.part_id for item in inventories})
        parts = await self._catalog.list_parts(part_ids)
        return {part.id: part.unit for part in parts}

    async def summary(self, warehouse_id: str | None = None) -> InventorySummary:
        inventories = await self._repository.list_all(warehouse_id, None)
        return summarize_inventory(inventories, warehouse_id)
