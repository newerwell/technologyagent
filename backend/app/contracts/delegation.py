"""P07 专家委派的结构化边界。"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DelegationRequest(_Strict):
    owner_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    task: str = Field(min_length=1, max_length=2000)
    data_scope: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    preferences: dict[str, Any] = Field(default_factory=dict)
    specialist: Literal["analyst", "order"]
    parent_call_id: str = Field(min_length=1)


class DelegationResult(_Strict):
    status: Literal["completed", "failed", "waiting_input"]
    summary: str = ""
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    pending_interrupt: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
