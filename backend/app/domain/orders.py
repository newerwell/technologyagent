"""P04 订单事实校验；不信任模型给出的金额、供应商或报价字段。"""

from __future__ import annotations

import hashlib
import json

from backend.app.contracts.common import AppError, ErrorCodes
from backend.app.contracts.domain import OrderDraft, OrderItem, Quote, Supplier


def build_order_item(part_id: str, quantity: int, quote: Quote) -> OrderItem:
    if quantity < 1:
        raise AppError(ErrorCodes.VALIDATION_ERROR, "quantity must be positive", http_status=422)
    return OrderItem(
        part_id=part_id,
        quantity=quantity,
        unit_price_cents=quote.unit_price_cents,
        quote_id=quote.id,
        line_total_cents=quantity * quote.unit_price_cents,
    )


def validate_supplier(supplier: Supplier) -> None:
    if supplier.status != "active":
        raise AppError(ErrorCodes.VALIDATION_ERROR, "supplier is inactive", http_status=422)


def serialize_draft(draft: OrderDraft) -> dict:
    return {
        **draft.model_dump(mode="json"),
        "snapshot_versions": draft.snapshot_versions,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }


def quote_snapshot(quote: Quote) -> str:
    """Hash every quote field that can change the approved purchasing decision."""
    payload = quote.model_dump(mode="json")
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
