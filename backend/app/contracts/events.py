"""P02 共享事件、run/message DTO 与 chat 请求契约。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.contracts.workflow import (
    PlanItem,
    ReviewCheck,
    ReviewResult,
    SourceRef,
    TaskType,
    WorkflowPhase,
)

RunStatus = Literal["created", "running", "waiting_input", "completed", "failed", "cancelled"]
EventType = Literal[
    "run_started",
    "token",
    "tool_started",
    "tool_finished",
    "interrupt",
    "phase",
    "plan",
    "review",
    "artifact_ready",
    "error",
    "run_finished",
    "stream_end",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunStartedPayload(_Strict):
    status: RunStatus
    thread_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    model_mode: Literal["fake", "live"] = "fake"


class TokenPayload(_Strict):
    message_id: str = Field(min_length=1)
    delta: str = Field(min_length=1)
    actor: Literal["main", "analyst", "order"] = "main"


class ToolStartedPayload(_Strict):
    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    actor: Literal["main", "analyst", "order"] = "main"
    args_summary: dict[str, Any] = Field(default_factory=dict)
    simulation: bool = False


class ToolFinishedPayload(_Strict):
    call_id: str = Field(min_length=1)
    status: Literal["success", "error"]
    result_summary: str = ""
    source: str = ""
    error: str | None = None
    simulation: bool = False


class InterruptPayload(_Strict):
    interrupt_id: str = Field(min_length=1)
    kind: Literal["approval", "supplement"]
    draft_id: str | None = None
    version: int | None = Field(default=None, ge=1)
    fields: list[str] | None = None
    summary: str = ""


class PhasePayload(_Strict):
    phase: WorkflowPhase
    iteration: int = Field(default=0, ge=0)
    task_type: TaskType = "general"
    revision_count: int = Field(default=0, ge=0, le=2)


class PlanPayload(_Strict):
    items: list[PlanItem] = Field(default_factory=list)
    task_type: TaskType = "general"
    request_constraints: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[SourceRef] = Field(default_factory=list)


class ReviewPayload(_Strict):
    passed: bool
    checks: list[str] = Field(default_factory=list)
    revision_count: int = Field(default=0, ge=0, le=2)
    details: list[ReviewCheck] = Field(default_factory=list)
    result: ReviewResult | None = None
    incomplete_items: list[str] = Field(default_factory=list)


class ArtifactReadyPayload(_Strict):
    artifact_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    mime: str = "application/octet-stream"
    source_refs: list[dict[str, str]] = Field(default_factory=list)


class ErrorPayload(_Strict):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool = False


class RunFinishedPayload(_Strict):
    status: Literal["completed", "failed", "cancelled"]
    summary: str = ""
    review_passed: bool | None = None
    committed_facts: bool = False


class StreamEndPayload(_Strict):
    reason: Literal["completed", "failed", "cancelled", "waiting_input"]
    last_seq: int = Field(ge=1)


PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "run_started": RunStartedPayload,
    "token": TokenPayload,
    "tool_started": ToolStartedPayload,
    "tool_finished": ToolFinishedPayload,
    "interrupt": InterruptPayload,
    "phase": PhasePayload,
    "plan": PlanPayload,
    "review": ReviewPayload,
    "artifact_ready": ArtifactReadyPayload,
    "error": ErrorPayload,
    "run_finished": RunFinishedPayload,
    "stream_end": StreamEndPayload,
}


class EventEnvelope(_Strict):
    schema_version: Literal[1] = 1
    type: EventType
    event_id: str = Field(min_length=1)
    seq: int = Field(ge=1)
    thread_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    at: AwareDatetime
    payload: dict[str, Any]

    @field_validator("at", mode="after")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _valid_payload(self) -> "EventEnvelope":
        model = PAYLOAD_MODELS[self.type]
        model.model_validate(self.payload)
        return self


class MessageView(_Strict):
    id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    role: Literal["user", "assistant"]
    content: str
    created_at: AwareDatetime
    model_mode: Literal["fake", "live"] | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class RunView(_Strict):
    id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    graph_version: Literal["v1", "v2"] = "v1"
    skill_manifest: list[dict[str, str]] = Field(default_factory=list)
    specialist_trace: list[dict[str, Any]] = Field(default_factory=list)
    status: RunStatus
    phase: WorkflowPhase | None = None
    task_type: TaskType = "general"
    plan: list[PlanItem] = Field(default_factory=list)
    evidence_refs: list[SourceRef] = Field(default_factory=list)
    review: ReviewResult | None = None
    revision_count: int = Field(default=0, ge=0, le=2)
    last_seq: int = Field(ge=0)
    cancel_requested: bool = False
    available_actions: list[str] = Field(default_factory=list)
    error_code: str | None = None
    summary: str = ""
    committed_facts: bool = False
    created_at: AwareDatetime
    updated_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    pending_interrupt: InterruptPayload | None = None


class ThreadView(_Strict):
    id: str = Field(min_length=1)
    title: str
    active_run_id: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ConversationView(_Strict):
    thread: ThreadView
    messages: list[MessageView] = Field(default_factory=list)
    latest_run: RunView | None = None


class ChatRequest(_Strict):
    thread_id: str | None = Field(default=None, min_length=1)
    message: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(min_length=1, max_length=128)


class DeleteResult(_Strict):
    deleted: bool
