"""Serialize business tool results without duplicating server-only review indexes."""

import json

from backend.app.contracts.agent import ModelToolCall
from backend.app.ports.tools import ToolResult


def serialize_tool_result(call: ModelToolCall, result: ToolResult) -> str:
    """Keep every returned business field and source; retain review facts on server.

    ``evidence_refs`` contains derived numeric facts with repeated source lists.
    It is consumed by the plan/reviewer, not part of the business tool response.
    Sending it alongside the original rows makes model context grow quadratically.
    Build a metadata copy so authorization, plan and review inputs stay unchanged.
    """
    meta = {key: value for key, value in result.meta.items() if key != "evidence_refs"}
    return json.dumps(
        {"call_id": result.call_id or call.id, "ok": result.ok,
         "data": result.data, "error": result.error, "meta": meta},
        ensure_ascii=False, default=str,
    )
