"""补货预览用例：一次拉齐范围、报价、供应商，纯函数计算。"""

from __future__ import annotations

from backend.app.contracts.common import Clock, RequestContext
from backend.app.contracts.domain import (
    PreviewLine,
    PreviewResult,
    Quote,
    ReplenishmentRequest,
    SourceRef,
)
from backend.app.domain.replenishment import calculate_replenishment
from backend.app.ports.catalog import CatalogReader
from backend.app.ports.inventory import InventoryReader

DATA_SOURCE = "local_seed"


class ReplenishmentService:
    def __init__(
        self,
        catalog: CatalogReader,
        inventory: InventoryReader,
        clock: Clock,
    ) -> None:
        self._catalog = catalog
        self._inventory = inventory
        self._clock = clock

    async def preview(
        self, request: ReplenishmentRequest, ctx: RequestContext
    ) -> PreviewResult:
        now = self._clock.now()
        parts = {part.id: part for part in await self._catalog.list_parts(request.part_ids)}
        inventories = {
            inventory.part_id: inventory
            for inventory in await self._inventory.list_scope(
                request.part_ids, request.warehouse_id
            )
        }
        quotes = await self._catalog.list_quotes(request.part_ids)
        quotes_by_part: dict[str, list[Quote]] = {}
        for quote in quotes:
            quotes_by_part.setdefault(quote.part_id, []).append(quote)
        supplier_ids = sorted({quote.supplier_id for quote in quotes})
        suppliers = await self._catalog.list_suppliers(supplier_ids)

        lines: list[PreviewLine] = []
        snapshot_versions: dict[str, int] = {}
        source_refs: list[SourceRef] = []
        for part_id in request.part_ids:
            part = parts.get(part_id)
            inventory = inventories.get(part_id)
            if part is None:
                lines.append(
                    PreviewLine(
                        part_id=part_id,
                        warehouse_id=request.warehouse_id,
                        available=0,
                        projected=0,
                        shortage=0,
                        warning=False,
                        quantity=0,
                        total_cents=0,
                        actionable=False,
                        missing_fields=["part"],
                    )
                )
                continue
            if inventory is None:
                lines.append(
                    PreviewLine(
                        part_id=part_id,
                        part_name=part.name,
                        warehouse_id=request.warehouse_id,
                        unit=part.unit,
                        available=0,
                        projected=0,
                        shortage=0,
                        warning=False,
                        quantity=0,
                        total_cents=0,
                        actionable=False,
                        missing_fields=["inventory"],
                    )
                )
                continue
            line = calculate_replenishment(
                inventory,
                quotes_by_part.get(part_id, []),
                suppliers,
                request.max_lead_days,
                now,
                part_name=part.name,
                unit=part.unit,
            )
            lines.append(line)
            snapshot_versions[inventory.id] = inventory.version
            source_refs.append(
                SourceRef(
                    call_id=ctx.call_id,
                    entity="inventory",
                    id=inventory.id,
                    data_source=DATA_SOURCE,
                    as_of=now,
                )
            )
            for quote in quotes_by_part.get(part_id, []):
                source_refs.append(
                    SourceRef(
                        call_id=ctx.call_id,
                        entity="quote",
                        id=quote.id,
                        data_source=DATA_SOURCE,
                        as_of=now,
                    )
                )
        return PreviewResult(
            lines=lines,
            snapshot_versions=snapshot_versions,
            source_refs=source_refs,
        )
