"""P05结构化工作流契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TaskType = Literal["general", "inventory", "order", "analysis", "supplier"]
PlanStatus = Literal["pending", "running", "done", "failed", "skipped"]
WorkflowPhase = Literal["planning", "executing", "reviewing", "result"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceRef(_Strict):
    call_id: str = Field(min_length=1)
    entity: str = Field(min_length=1)
    id: str = Field(min_length=1)
    data_source: str = "local_seed"
    as_of: str | None = None


class QueryEvidence(_Strict):
    """Successful query-level evidence, including valid empty/paged results."""

    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    data_source: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    as_of: str | None = None
    total: int | None = Field(default=None, ge=0)


class PlanItem(_Strict):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    status: PlanStatus = "pending"
    evidence_refs: list[SourceRef] = Field(default_factory=list)
    query_evidence: list[QueryEvidence] = Field(default_factory=list)
    required_action: str | None = None


class ReviewCheck(_Strict):
    check_id: str = Field(min_length=1)
    passed: bool
    reason: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    kind: Literal["deterministic", "semantic"] = "deterministic"


class ReviewResult(_Strict):
    passed: bool
    checks: list[ReviewCheck] = Field(default_factory=list)
    needs_revision: bool = False
    revision_count: int = Field(default=0, ge=0, le=2)
    incomplete_items: list[str] = Field(default_factory=list)


class HarnessSnapshot(_Strict):
    task_type: TaskType = "general"
    phase: WorkflowPhase | None = None
    plan: list[PlanItem] = Field(default_factory=list)
    evidence_refs: list[SourceRef] = Field(default_factory=list)
    review: ReviewResult | None = None
    revision_count: int = Field(default=0, ge=0, le=2)


def source_refs(values: list[dict[str, Any]]) -> list[SourceRef]:
    """只导出真实记录引用；数值事实无id时不伪造来源。"""
    refs: list[SourceRef] = []
    for value in values:
        if not value.get("id") or not value.get("call_id") or not value.get("entity"):
            continue
        refs.append(SourceRef.model_validate({
            "call_id": str(value["call_id"]),
            "entity": str(value["entity"]),
            "id": str(value["id"]),
            "data_source": str(value.get("data_source") or "local_seed"),
            "as_of": value.get("as_of"),
        }))
    unique: dict[tuple[str, str, str], SourceRef] = {}
    for ref in refs:
        unique[(ref.call_id, ref.entity, ref.id)] = ref
    return list(unique.values())
