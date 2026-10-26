"""Strict shared canonicalization for receipt proposal and execution facts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, ValidationError, Field

from backend.app.contracts.common import AppError, ErrorCodes


class ReceiptLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    part_id: StrictStr = Field(min_length=1)
    quantity: StrictInt = Field(gt=0)


class ReceiptInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    order_id: StrictStr = Field(min_length=1)
    receipt_id: StrictStr = Field(min_length=1)
    warehouse_id: StrictStr = Field(min_length=1)
    items: list[ReceiptLineInput] = Field(min_length=1)


def canonicalize_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge duplicate lines and sort by part id before hashing, approval, or write."""
    try:
        receipt = ReceiptInput.model_validate(payload)
    except ValidationError as exc:
        raise AppError(ErrorCodes.VALIDATION_ERROR, "invalid receipt facts", 422) from exc
    quantities: dict[str, int] = {}
    for item in receipt.items:
        quantities[item.part_id] = quantities.get(item.part_id, 0) + item.quantity
    return {"order_id": receipt.order_id, "receipt_id": receipt.receipt_id,
            "warehouse_id": receipt.warehouse_id,
            "items": [{"part_id": part_id, "quantity": quantities[part_id]}
                      for part_id in sorted(quantities)]}
