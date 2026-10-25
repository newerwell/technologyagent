"""P01 业务实体、请求与预览契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

from backend.app.contracts.common import PageQuery


class _Entity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1


class Part(_Entity):
    id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    specification: str = ""
    unit: str = Field(min_length=1)
    category: str = ""
    active: bool = True


class Supplier(_Entity):
    id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    status: Literal["active", "inactive"]
    credit_rating: str | None = None


class Quote(_Entity):
    id: str = Field(min_length=1)
    part_id: str = Field(min_length=1)
    supplier_id: str = Field(min_length=1)
    unit_price_cents: int = Field(gt=0)
    min_order_qty: int = Field(ge=1)
    lead_days: int = Field(ge=0)
    valid_until: AwareDatetime
    currency: Literal["CNY"] = "CNY"


class Inventory(_Entity):
    id: str = Field(min_length=1)
    part_id: str = Field(min_length=1)
    warehouse_id: str = Field(min_length=1)
    on_hand: int = Field(ge=0)
    reserved: int = Field(ge=0)
    inbound: int = Field(ge=0)
    safety_stock: int = Field(ge=0)
    target_stock: int = Field(ge=0)
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def _valid_stock(self) -> "Inventory":
        if self.reserved > self.on_hand:
            raise ValueError("reserved must not exceed on_hand")
        if self.target_stock < self.safety_stock:
            raise ValueError("target_stock must be >= safety_stock")
        return self


class SourceRef(_Entity):
    call_id: str | None = None
    entity: str = Field(min_length=1)
    id: str = Field(min_length=1)
    data_source: Literal["local_seed", "local_snapshot", "remote_erp"]
    as_of: AwareDatetime


class OrderItem(_Entity):
    part_id: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    unit_price_cents: int = Field(gt=0)
    quote_id: str = Field(min_length=1)
    line_total_cents: int = Field(gt=0)

    @model_validator(mode="after")
    def _valid_line_total(self) -> "OrderItem":
        if self.line_total_cents != self.quantity * self.unit_price_cents:
            raise ValueError("line_total_cents must equal quantity * unit_price_cents")
        return self


class PurchaseOrderItem(OrderItem):
    received_qty: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _valid_received(self) -> "PurchaseOrderItem":
        if self.received_qty > self.quantity:
            raise ValueError("received_qty must not exceed quantity")
        return self


class OrderDraft(_Entity):
    id: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    supplier_id: str = Field(min_length=1)
    warehouse_id: str = Field(min_length=1)
    items: list[OrderItem] = Field(min_length=1)
    total_cents: int = Field(ge=0)
    version: int = Field(ge=1)
    state: Literal["draft", "pending_approval", "approved", "rejected", "superseded"]
    source_refs: list[SourceRef] = Field(default_factory=list)
    # P04 persistence metadata is omitted from the frozen P01 fixture hash.
    snapshot_versions: dict[str, int] = Field(default_factory=dict, exclude=True)
    quote_snapshots: SkipJsonSchema[dict[str, str]] = Field(default_factory=dict, exclude=True)
    created_at: AwareDatetime | None = Field(default=None, exclude=True)
    updated_at: AwareDatetime | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _valid_total(self) -> "OrderDraft":
        if self.total_cents != sum(item.line_total_cents for item in self.items):
            raise ValueError("total_cents must equal sum of line totals")
        return self


class PurchaseOrder(_Entity):
    id: str = Field(min_length=1)
    number: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)
    supplier_id: str = Field(min_length=1)
    warehouse_id: str = Field(min_length=1)
    items: list[PurchaseOrderItem] = Field(min_length=1)
    total_cents: int = Field(ge=0)
    status: Literal["submitted", "shipped", "received", "completed", "cancelled"]
    version: int = Field(ge=1)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _valid_total(self) -> "PurchaseOrder":
        if self.total_cents != sum(item.line_total_cents for item in self.items):
            raise ValueError("total_cents must equal sum of line totals")
        return self


class InventoryQuery(PageQuery):
    warehouse_id: str | None = None
    part_name: str | None = None


class ReplenishmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    part_ids: list[str] = Field(min_length=1, max_length=50)
    warehouse_id: str = Field(min_length=1)
    max_lead_days: int | None = Field(default=None, ge=0)

    @field_validator("part_ids")
    @classmethod
    def _unique_part_ids(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("part_ids must not contain empty strings")
        if len(set(value)) != len(value):
            raise ValueError("part_ids must not contain duplicates")
        return value


class CandidateQuote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    quote_id: str
    supplier_id: str
    supplier_name: str
    unit_price_cents: int
    min_order_qty: int
    lead_days: int
    valid_until: datetime
    suggested_quantity: int = Field(ge=0)
    line_total_cents: int = Field(ge=0)

    @model_validator(mode="after")
    def _valid_candidate_total(self) -> "CandidateQuote":
        if self.line_total_cents != self.suggested_quantity * self.unit_price_cents:
            raise ValueError("candidate line total must equal suggested quantity * unit price")
        return self


class PreviewLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    part_id: str
    part_name: str | None = None
    inventory_id: str | None = None
    warehouse_id: str
    unit: str | None = None
    available: int = Field(ge=0)
    projected: int = Field(ge=0)
    shortage: int = Field(ge=0)
    warning: bool
    candidate_quotes: list[CandidateQuote] = Field(default_factory=list)
    recommended_quote_id: str | None = None
    quantity: int = Field(ge=0)
    total_cents: int = Field(ge=0)
    actionable: bool
    missing_fields: list[str] = Field(default_factory=list)
    inventory_version: int | None = None


class PreviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[PreviewLine]
    snapshot_versions: dict[str, int] = Field(default_factory=dict)
    source_refs: list[SourceRef] = Field(default_factory=list)


class InventoryView(Inventory):
    unit: str | None = None
    available: int = Field(ge=0)
    projected: int = Field(ge=0)
    shortage: int = Field(ge=0)
    warning: bool

    @model_validator(mode="after")
    def _valid_derived(self) -> "InventoryView":
        if self.available != self.on_hand - self.reserved:
            raise ValueError("available must equal on_hand - reserved")
        if self.projected != self.available + self.inbound:
            raise ValueError("projected must equal available + inbound")
        if self.shortage != max(0, self.target_stock - self.projected):
            raise ValueError("shortage must equal max(0, target_stock - projected)")
        if self.warning != (self.projected < self.safety_stock):
            raise ValueError("warning must equal projected < safety_stock")
        return self


class QuoteView(Quote):
    part_name: str
    part_unit: str
    supplier_name: str
    supplier_status: Literal["active", "inactive"]
    is_valid: bool


class InventorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    warehouse_id: str | None = None
    records: int = Field(ge=0)
    warehouses: int = Field(ge=0)
    total_on_hand: int = Field(ge=0)
    total_reserved: int = Field(ge=0)
    total_inbound: int = Field(ge=0)
    total_available: int = Field(ge=0)
    total_projected: int = Field(ge=0)
    total_safety_stock: int = Field(ge=0)
    total_target_stock: int = Field(ge=0)
    total_shortage: int = Field(ge=0)
    warning_count: int = Field(ge=0)
