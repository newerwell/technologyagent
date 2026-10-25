"""P02 执行器输入/输出契约；P03 再增加模型与工具类型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.contracts.common import RequestContext


class ExecutorInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    run_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=4000)
    ctx: RequestContext
    graph_version: Literal["v1", "v2"] = "v1"
    skill_context: str = Field(default="", max_length=12000)
    request_constraints: dict[str, Any] | None = None


class ModelToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = ""
    name: str = ""
    arguments: str = ""
    index: int | None = None


class ModelMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ModelToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


class ModelDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["token", "tool_call", "usage"]
    content: str | None = None
    tool_call: ModelToolCall | None = None
    usage: dict[str, Any] | None = None


class ExecutionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["completed", "failed", "cancelled", "waiting_input"]
    summary: str = ""
    error_code: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    committed_facts: bool = False
    pending_interrupt: dict[str, Any] | None = None
