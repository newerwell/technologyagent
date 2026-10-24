"""P03 LangGraph v1 状态子集；P05 再增加 plan/review 字段。"""

from __future__ import annotations

from typing import Any, TypedDict

from backend.app.contracts.agent import ModelMessage, ModelToolCall


class AgentStateV1(TypedDict, total=False):
    messages: list[ModelMessage]
    pending_tool_calls: list[ModelToolCall]
    final_answer: str
    evidence: list[dict[str, Any]]
    tool_error: bool
    usage: dict[str, Any] | None
