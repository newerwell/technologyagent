"""补货服务的策略边界；不依赖数据库或用户库存。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.contracts.common import AppError, FixedClock, RequestContext
from backend.app.contracts.domain import Inventory, Part, Quote, ReplenishmentRequest, Supplier
from backend.app.contracts.order_workflow import DraftPrepareRequest
from backend.app.services.drafts import DraftService
from backend.app.services.replenishment import ReplenishmentService

NOW = datetime(2026, 10, 23, 2, 0, tzinfo=timezone.utc)


class MemoryCatalog:
    def __init__(self, parts: list[Part]) -> None:
        self.parts = parts

    async def list_parts(self, ids: list[str]) -> list[Part]:
        return [part for part in self.parts if part.id in ids]

    async def list_quotes(self, ids: list[str]) -> list[Quote]:
        return [Quote(id=f"Q-{part_id}", part_id=part_id, supplier_id="S1",
            unit_price_cents=1200, min_order_qty=1, lead_days=2,
            valid_until=datetime(2026, 12, 31, tzinfo=timezone.utc)) for part_id in ids]

    async def list_suppliers(self, ids: list[str]) -> list[Supplier]:
        return [Supplier(id="S1", code="S1", name="供应商一", status="active")]


class MemoryInventory:
    async def list_scope(self, ids: list[str], warehouse_id: str) -> list[Inventory]:
        return [Inventory(id=f"I-{part_id}", part_id=part_id, warehouse_id=warehouse_id,
            on_hand=20, reserved=5, inbound=10, safety_stock=30, target_stock=80, version=1)
            for part_id in ids]


def context() -> RequestContext:
    return RequestContext(owner_id="owner-1", request_id="request-1")


@pytest.mark.asyncio
async def test_inactive_part_keeps_inventory_facts_but_cannot_be_recommended():
    catalog = MemoryCatalog([
        Part(id="P001", code="P001", name="停用件", unit="套", active=False),
    ])
    service = ReplenishmentService(catalog, MemoryInventory(), FixedClock(NOW))

    result = await service.preview(ReplenishmentRequest(part_ids=["P001"], warehouse_id="W01"), context())

    line = result.lines[0]
    assert (line.available, line.projected, line.shortage, line.warning) == (15, 25, 55, True)
    assert not line.actionable
    assert (line.quantity, line.total_cents, line.recommended_quote_id, line.candidate_quotes) == (0, 0, None, [])
    assert "part_inactive" in line.missing_fields


@pytest.mark.asyncio
async def test_mixed_active_and_inactive_parts_are_independently_actionable():
    catalog = MemoryCatalog([
        Part(id="P001", code="P001", name="停用件", unit="套", active=False),
        Part(id="P002", code="P002", name="启用件", unit="件", active=True),
    ])
    service = ReplenishmentService(catalog, MemoryInventory(), FixedClock(NOW))

    result = await service.preview(ReplenishmentRequest(part_ids=["P001", "P002"], warehouse_id="W01"), context())

    inactive, active = result.lines
    assert not inactive.actionable and inactive.shortage == 55
    assert active.actionable and active.shortage == 55 and active.recommended_quote_id == "Q-P002"


@pytest.mark.asyncio
async def test_inactive_part_draft_is_rejected_before_preview_or_persistence():
    catalog = MemoryCatalog([Part(id="P001", code="P001", name="停用件", unit="套", active=False)])

    class PreviewMustNotRun:
        async def preview(self, *_args):
            raise AssertionError("inactive part must be rejected before draft preparation")

    service = DraftService(None, catalog, PreviewMustNotRun(), FixedClock(NOW))

    with pytest.raises(AppError) as caught:
        await service.prepare(DraftPrepareRequest(part_ids=["P001"], warehouse_id="W01"), context())

    assert caught.value.http_status == 409
    assert caught.value.message == "inactive parts cannot be ordered"
