"""确定性补货规则：可用量、预计可用量、缺口、报价过滤与推荐。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.app.contracts.domain import (
    CandidateQuote,
    Inventory,
    InventorySummary,
    PreviewLine,
    Quote,
    Supplier,
)
from backend.app.domain.money import line_total


@dataclass(frozen=True, slots=True)
class StockState:
    available: int
    projected: int
    shortage: int
    warning: bool


def _validate_inventory(inventory: Inventory) -> None:
    if inventory.on_hand < 0 or inventory.reserved < 0 or inventory.inbound < 0:
        raise ValueError("inventory quantities must be non-negative")
    if inventory.reserved > inventory.on_hand:
        raise ValueError("reserved must not exceed on_hand")
    if inventory.target_stock < inventory.safety_stock:
        raise ValueError("target_stock must be >= safety_stock")


def stock_state(inventory: Inventory) -> StockState:
    _validate_inventory(inventory)
    available = inventory.on_hand - inventory.reserved
    projected = available + inventory.inbound
    shortage = max(0, inventory.target_stock - projected)
    warning = projected < inventory.safety_stock
    return StockState(
        available=available,
        projected=projected,
        shortage=shortage,
        warning=warning,
    )


def _ensure_aware(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")


def _valid_quotes(
    quotes: list[Quote],
    suppliers: list[Supplier],
    max_lead_days: int | None,
    now: datetime,
) -> list[Quote]:
    supplier_by_id = {supplier.id: supplier for supplier in suppliers}
    eligible: list[Quote] = []
    for quote in quotes:
        supplier = supplier_by_id.get(quote.supplier_id)
        if supplier is None or supplier.status != "active":
            continue
        if quote.currency != "CNY":
            continue
        # valid_until 等于当前时刻视为过期。
        if quote.valid_until <= now:
            continue
        if max_lead_days is not None and quote.lead_days > max_lead_days:
            continue
        eligible.append(quote)
    eligible.sort(
        key=lambda quote: (
            quote.unit_price_cents,
            quote.lead_days,
            quote.supplier_id,
            quote.id,
        )
    )
    return eligible


def calculate_replenishment(
    inventory: Inventory,
    quotes: list[Quote],
    suppliers: list[Supplier],
    max_lead_days: int | None,
    now: datetime,
    *,
    part_name: str | None = None,
    unit: str | None = None,
) -> PreviewLine:
    """纯函数：不访问数据库/模型，所有金额使用整数分。"""
    _ensure_aware(now)
    state = stock_state(inventory)
    valid = _valid_quotes(quotes, suppliers, max_lead_days, now)
    supplier_by_id = {supplier.id: supplier for supplier in suppliers}

    candidates: list[CandidateQuote] = []
    for quote in valid:
        suggested = max(state.shortage, quote.min_order_qty) if state.shortage > 0 else 0
        candidates.append(
            CandidateQuote(
                quote_id=quote.id,
                supplier_id=quote.supplier_id,
                supplier_name=supplier_by_id[quote.supplier_id].name,
                unit_price_cents=quote.unit_price_cents,
                min_order_qty=quote.min_order_qty,
                lead_days=quote.lead_days,
                valid_until=quote.valid_until,
                suggested_quantity=suggested,
                line_total_cents=line_total(suggested, quote.unit_price_cents),
            )
        )

    if state.shortage == 0:
        return PreviewLine(
            part_id=inventory.part_id,
            part_name=part_name,
            inventory_id=inventory.id,
            warehouse_id=inventory.warehouse_id,
            unit=unit,
            available=state.available,
            projected=state.projected,
            shortage=0,
            warning=state.warning,
            candidate_quotes=candidates,
            recommended_quote_id=None,
            quantity=0,
            total_cents=0,
            actionable=False,
            missing_fields=[],
            inventory_version=inventory.version,
        )

    if not candidates:
        return PreviewLine(
            part_id=inventory.part_id,
            part_name=part_name,
            inventory_id=inventory.id,
            warehouse_id=inventory.warehouse_id,
            unit=unit,
            available=state.available,
            projected=state.projected,
            shortage=state.shortage,
            warning=state.warning,
            candidate_quotes=[],
            recommended_quote_id=None,
            quantity=0,
            total_cents=0,
            actionable=False,
            missing_fields=["valid_quote"],
            inventory_version=inventory.version,
        )

    recommended = candidates[0]
    return PreviewLine(
        part_id=inventory.part_id,
        part_name=part_name,
        inventory_id=inventory.id,
        warehouse_id=inventory.warehouse_id,
        unit=unit,
        available=state.available,
        projected=state.projected,
        shortage=state.shortage,
        warning=state.warning,
        candidate_quotes=candidates,
        recommended_quote_id=recommended.quote_id,
        quantity=recommended.suggested_quantity,
        total_cents=recommended.line_total_cents,
        actionable=True,
        missing_fields=[],
        inventory_version=inventory.version,
    )


def summarize_inventory(inventories: list[Inventory], warehouse_id: str | None = None) -> InventorySummary:
    """汇总全部匹配记录，不使用分页结果充当全量。"""
    states = [(inventory, stock_state(inventory)) for inventory in inventories]
    records = len(states)
    warehouses = len({inventory.warehouse_id for inventory, _ in states})
    return InventorySummary(
        warehouse_id=warehouse_id,
        records=records,
        warehouses=warehouses,
        total_on_hand=sum(inventory.on_hand for inventory, _ in states),
        total_reserved=sum(inventory.reserved for inventory, _ in states),
        total_inbound=sum(inventory.inbound for inventory, _ in states),
        total_available=sum(state.available for _, state in states),
        total_projected=sum(state.projected for _, state in states),
        total_safety_stock=sum(inventory.safety_stock for inventory, _ in states),
        total_target_stock=sum(inventory.target_stock for inventory, _ in states),
        total_shortage=sum(state.shortage for _, state in states),
        warning_count=sum(1 for _, state in states if state.warning),
    )
