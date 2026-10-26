"""只读run诊断响应契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ToolCallTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str
    tool_name: str
    actor: str
    parent_call_id: str | None = None
    status: Literal["running", "success", "error"]
    source: str | None = None
    duration_ms: float | None = None
    error_code: str | None = None


class RunTraceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    thread_id: str
    request_id: str | None = None
    status: str
    phase: str | None = None
    created_at: Any
    finished_at: Any = None
    duration_ms: float | None = None
    model: dict[str, Any]
    tools: dict[str, int]
    tool_calls: list[ToolCallTrace]
    phases: list[str]
    phase_trace: list[dict[str, Any]]
    errors: list[dict[str, str]]
    approvals: dict[str, int]
    artifacts: list[dict[str, Any]]
    data_sources: dict[str, int]
    business_effects: dict[str, int | bool]
    committed_facts: bool
    recovery: dict[str, str | bool]
