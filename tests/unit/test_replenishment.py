"""P01 确定性补货规则。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.contracts.domain import Inventory, Quote, Supplier
from backend.app.domain.replenishment import calculate_replenishment, stock_state, summarize_inventory

NOW = datetime(2026, 10, 23, 2, 0, 0, tzinfo=timezone.utc)
FUTURE = datetime(2026, 12, 31, 15, 59, 59, tzinfo=timezone.utc)
PAST = datetime(2026, 10, 22, 15, 59, 59, tzinfo=timezone.utc)


def supplier(supplier_id: str, status: str = "active") -> Supplier:
    return Supplier(id=supplier_id, code=supplier_id, name=f"供应商{supplier_id}", status=status)


def quote(
    quote_id: str,
    part_id: str,
    supplier_id: str,
    price: int,
    moq: int,
    lead: int,
    valid_until: datetime = FUTURE,
) -> Quote:
    return Quote(
        id=quote_id,
        part_id=part_id,
        supplier_id=supplier_id,
        unit_price_cents=price,
        min_order_qty=moq,
        lead_days=lead,
        valid_until=valid_until,
    )


def inventory(
    *,
    inventory_id: str = "I001",
    part_id: str = "P001",
    warehouse_id: str = "W01",
    on_hand: int = 20,
    reserved: int = 5,
    inbound: int = 10,
    safety: int = 30,
    target: int = 80,
) -> Inventory:
    return Inventory(
        id=inventory_id,
        part_id=part_id,
        warehouse_id=warehouse_id,
        on_hand=on_hand,
        reserved=reserved,
        inbound=inbound,
        safety_stock=safety,
        target_stock=target,
        version=1,
    )


def p001_quotes() -> list[Quote]:
    return [
        quote("Q01", "P001", "S01", 1200, 10, 5),
        quote("Q02", "P001", "S02", 1100, 1, 12),
        quote("Q03", "P001", "S03", 900, 1, 2, PAST),
    ]


def test_p001_price_priority_selects_s02():
    line = calculate_replenishment(
        inventory(), p001_quotes(), [supplier("S01"), supplier("S02"), supplier("S03")], None, NOW,
        part_name="刹车片", unit="套",
    )
    assert (line.available, line.projected, line.shortage) == (15, 25, 55)
    assert line.warning is True
    assert (line.recommended_quote_id, line.quantity, line.total_cents) == ("Q02", 55, 60500)
    assert [c.quote_id for c in line.candidate_quotes] == ["Q02", "Q01"]
    assert line.actionable is True


def test_p001_with_7_day_limit_selects_s01():
    line = calculate_replenishment(
        inventory(), p001_quotes(), [supplier("S01"), supplier("S02"), supplier("S03")], 7, NOW
    )
    assert (line.recommended_quote_id, line.quantity, line.total_cents) == ("Q01", 55, 66000)
    assert [c.quote_id for c in line.candidate_quotes] == ["Q01"]


def test_threshold_equal_is_not_warning():
    p002 = inventory(
        inventory_id="I004", part_id="P002", warehouse_id="W02",
        on_hand=10, reserved=0, inbound=5, safety=15, target=30,
    )
    quotes = [
        quote("Q04", "P002", "S01", 800, 20, 3),
        quote("Q05", "P002", "S02", 850, 1, 8),
    ]
    line = calculate_replenishment(p002, quotes, [supplier("S01"), supplier("S02")], None, NOW)
    assert line.projected == 15
    assert line.warning is False
    assert line.shortage == 15
    assert (line.recommended_quote_id, line.quantity, line.total_cents) == ("Q04", 20, 16000)


def test_no_valid_quote_reports_missing_and_not_actionable():
    p003 = inventory(
        inventory_id="I005", part_id="P003", on_hand=5, reserved=1, inbound=0,
        safety=20, target=40,
    )
    line = calculate_replenishment(
        p003,
        [quote("Q06", "P003", "S03", 700, 1, 1, PAST)],
        [supplier("S03", "inactive")],
        None,
        NOW,
    )
    assert line.shortage == 36
    assert line.actionable is False
    assert line.missing_fields == ["valid_quote"]
    assert (line.quantity, line.total_cents, line.recommended_quote_id) == (0, 0, None)


def test_valid_until_equal_now_is_expired():
    line = calculate_replenishment(
        inventory(),
        [quote("Q01", "P001", "S01", 1200, 10, 5, NOW)],
        [supplier("S01")],
        None,
        NOW,
    )
    assert line.missing_fields == ["valid_quote"]
    assert line.actionable is False


def test_inactive_supplier_is_filtered():
    line = calculate_replenishment(
        inventory(), p001_quotes(), [supplier("S01"), supplier("S02", "inactive"), supplier("S03")], None, NOW
    )
    assert [c.quote_id for c in line.candidate_quotes] == ["Q01"]
    assert line.recommended_quote_id == "Q01"


def test_moq_is_minimum_not_pack_multiple():
    inv = inventory(part_id="P004", on_hand=8, reserved=2, inbound=0, safety=10, target=20)
    line = calculate_replenishment(
        inv,
        [quote("Q07", "P004", "S01", 5000, 20, 4)],
        [supplier("S01")],
        None,
        NOW,
    )
    assert line.shortage == 14
    assert (line.quantity, line.total_cents) == (20, 100000)


def test_no_shortage_does_not_create_purchase_quantity():
    inv = inventory(on_hand=100, reserved=0, inbound=0, safety=10, target=20)
    line = calculate_replenishment(inv, p001_quotes(), [supplier("S01"), supplier("S02"), supplier("S03")], None, NOW)
    assert line.shortage == 0
    assert line.quantity == 0
    assert line.total_cents == 0
    assert line.recommended_quote_id is None
    assert line.actionable is False


def test_quote_sort_tie_breaks_by_lead_supplier_and_id():
    inv = inventory(part_id="P009", on_hand=0, reserved=0, inbound=0, safety=1, target=10)
    quotes = [
        quote("Q11", "P009", "S02", 100, 1, 5),
        quote("Q10", "P009", "S01", 100, 1, 5),
        quote("Q12", "P009", "S01", 100, 1, 2),
    ]
    line = calculate_replenishment(inv, quotes, [supplier("S01"), supplier("S02")], None, NOW)
    assert [c.quote_id for c in line.candidate_quotes] == ["Q12", "Q10", "Q11"]


def test_invalid_inventory_is_rejected():
    inv = Inventory.model_construct(
        id="I999", part_id="P001", warehouse_id="W01", on_hand=1, reserved=5,
        inbound=0, safety_stock=10, target_stock=20, version=1, schema_version=1,
    )
    with pytest.raises(ValueError):
        stock_state(inv)


def test_summarize_inventory_uses_all_records():
    items = [
        inventory(inventory_id="I001", part_id="P001"),
        inventory(inventory_id="I002", part_id="P002", warehouse_id="W02", on_hand=30, reserved=0, inbound=0, safety=10, target=20),
    ]
    summary = summarize_inventory(items)
    assert (summary.records, summary.warehouses) == (2, 2)
    assert summary.total_on_hand == 50
    assert summary.total_available == 45
    assert summary.warning_count == 1
    assert summary.total_shortage == 55
