"""P08 generic mutation proposal HTTP contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from backend.app.contracts.common import AppError, ErrorCodes
from backend.app.contracts.receipts import canonicalize_receipt


class MutationProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any]


class MutationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: Literal["approve", "reject"]
    decision_key: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(default=1, ge=1)


class MutationExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    idempotency_key: str = Field(min_length=1, max_length=128)


class _StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SupplierCreatePayload(_StrictPayload):
    code: StrictStr = Field(min_length=1)
    name: StrictStr = Field(min_length=1)
    credit_rating: StrictStr | None = None


class SupplierStatusPayload(_StrictPayload):
    supplier_id: StrictStr = Field(min_length=1)
    status: Literal["active", "inactive"]


class PartCreatePayload(_StrictPayload):
    code: StrictStr = Field(min_length=1)
    name: StrictStr = Field(min_length=1)
    unit: StrictStr = Field(min_length=1)
    specification: StrictStr = ""
    category: StrictStr = ""


class InventoryMutationPayload(_StrictPayload):
    inventory_id: StrictStr = Field(min_length=1)
    quantity: StrictInt = Field(gt=0)
    expected_version: StrictInt = Field(ge=1)


class OrderStatusPayload(_StrictPayload):
    order_id: StrictStr = Field(min_length=1)
    status: Literal["submitted", "shipped", "received", "completed", "cancelled"]
    expected_version: StrictInt = Field(ge=1)


class AmendmentLinePayload(_StrictPayload):
    part_id: StrictStr = Field(min_length=1)
    quote_id: StrictStr = Field(min_length=1)
    quantity: StrictInt = Field(gt=0)


class OrderAmendmentPayload(_StrictPayload):
    order_id: StrictStr = Field(min_length=1)
    expected_version: StrictInt = Field(ge=1)
    items: list[AmendmentLinePayload] = Field(min_length=1)


_ACTION_PAYLOADS = {
    "supplier_create": SupplierCreatePayload,
    "supplier_update_status": SupplierStatusPayload,
    "part_create": PartCreatePayload,
    "inventory_inbound": InventoryMutationPayload,
    "inventory_outbound": InventoryMutationPayload,
    "order_update_status": OrderStatusPayload,
    "order_update": OrderAmendmentPayload,
}


def parse_mutation_payload(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate concrete business facts at proposal time and at stored-payload execution."""
    if action == "inventory_receive":
        return canonicalize_receipt(payload)
    schema = _ACTION_PAYLOADS.get(action)
    if schema is None:
        raise AppError(ErrorCodes.UNSUPPORTED_OPERATION, f"unsupported mutation action: {action}", 405)
    try:
        return schema.model_validate(payload).model_dump(mode="python")
    except ValidationError as exc:
        raise AppError(ErrorCodes.VALIDATION_ERROR, f"invalid {action} payload", 422) from exc
