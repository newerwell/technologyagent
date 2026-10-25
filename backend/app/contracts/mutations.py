"""P08 generic mutation proposal HTTP contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MutationProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any]


class MutationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: Literal["approve", "reject"]
    decision_key: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(default=1, ge=1)
