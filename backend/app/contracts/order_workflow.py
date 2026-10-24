"""P04 草稿、审批和幂等操作的 API 契约。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DraftPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    part_ids: list[str] = Field(min_length=1, max_length=50)
    warehouse_id: str | None = Field(default=None, min_length=1)
    supplier_id: str | None = Field(default=None, min_length=1)
    max_lead_days: int | None = Field(default=None, ge=0)
    quantities: dict[str, Annotated[int, Field(gt=0, strict=True)]] = Field(default_factory=dict)

    @field_validator("part_ids")
    @classmethod
    def unique_part_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(not part_id for part_id in value):
            raise ValueError("part_ids must be unique and non-empty")
        return value

    @field_validator("quantities")
    @classmethod
    def positive_quantities(cls, value: dict[str, int]) -> dict[str, int]:
        if any(quantity < 1 for quantity in value.values()):
            raise ValueError("quantities must be positive integers")
        return value


class DraftPreparation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drafts: list[dict]
    missing_fields: list[str] = Field(default_factory=list)


class DraftItemPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    part_id: str = Field(min_length=1)
    quote_id: str = Field(min_length=1)
    quantity: int = Field(ge=1, strict=True)


class DraftPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_version: int = Field(ge=1)
    supplier_id: str | None = Field(default=None, min_length=1)
    warehouse_id: str | None = Field(default=None, min_length=1)
    items: list[DraftItemPatch] = Field(min_length=1)


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    interrupt_id: str = Field(min_length=1)
    decision: Literal["approve", "reject", "edit", "supplement"]
    expected_version: int | None = Field(default=None, ge=1)
    payload: dict = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=128)


class OrderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    draft_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=128)


class WorkflowStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(min_length=1, max_length=128)
    thread_id: str | None = None
    draft: DraftPrepareRequest | None = None
