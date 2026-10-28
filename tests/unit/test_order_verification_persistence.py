from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.contracts.domain import OrderDraft, OrderItem
from backend.app.repositories.orders import OrderRepository


class MemoryCollection:
    def __init__(self) -> None:
        self.inserted = None

    async def insert_one(self, document, *, session):
        self.inserted = document


class MemoryDatabase:
    def __init__(self) -> None:
        self.orders = MemoryCollection()

    def __getitem__(self, name):
        assert name == "orders"
        return self.orders


class MemoryMongo:
    def __init__(self) -> None:
        self.db = MemoryDatabase()


@pytest.mark.asyncio
async def test_order_repository_persists_server_verification_facts_with_order_insert():
    now = datetime(2026, 10, 23, tzinfo=timezone.utc)
    verification_facts = {
        "schema_version": 1,
        "submitted_at": now,
        "request_constraints": {"max_lead_days": 7},
        "items": [{"part_id": "P001", "warehouse_id": "W01", "quantity": 55,
                   "unit": "套", "quote_id": "Q01", "supplier_id": "S01",
                   "lead_days": 5, "quote_observed_at": now}],
    }
    mongo = MemoryMongo()
    repository = OrderRepository(mongo)
    draft = OrderDraft(
        id="drf-1", owner_id="owner-1", supplier_id="S01", warehouse_id="W01",
        items=[OrderItem(part_id="P001", quantity=55, unit_price_cents=1200,
                         quote_id="Q01", line_total_cents=66000)],
        total_cents=66000, version=1, state="pending_approval",
    )

    await repository.create_from_draft(
        draft, "op-1", now, session=object(), verification_facts=verification_facts,
    )

    inserted = mongo.db.orders.inserted
    assert inserted is not None
    assert inserted["verification_facts"] == verification_facts
    assert inserted["items"][0]["quantity"] == 55
    assert inserted["total_cents"] == 66000
