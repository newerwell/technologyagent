"""LangGraph v1 状态。

新增 P05 字段均为可选，旧 Mongo checkpoint 仍能按 v1 状态加载。
"""

from __future__ import annotations

from typing import Any, TypedDict

from backend.app.contracts.agent import ModelMessage, ModelToolCall


class AgentStateV1(TypedDict, total=False):
    run_id: str
    thread_id: str
    owner_id: str
    graph_version: str
    task_type: str
    plan: list[dict[str, Any]]
    phase: str
    evidence_refs: list[dict[str, Any]]
    review: dict[str, Any] | None
    revision_count: int
    plan_signature: str
    pending_interrupt: dict[str, Any] | None
    last_mutation_result: dict[str, Any] | None
    run_status: str
    messages: list[ModelMessage]
    pending_tool_calls: list[ModelToolCall]
    final_answer: str
    evidence: list[dict[str, Any]]
    tool_error: bool
    usage: dict[str, Any] | None
