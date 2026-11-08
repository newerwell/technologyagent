"""独立冻结的P03只读图实现；保持历史v1节点与状态协议。"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from backend.app.agent.budget import RunBudget, RunCancelled, RunDeadlineExceeded, RunLimitExceeded
from backend.app.agent.evidence import collect_evidence
from backend.app.agent.harness import (
    build_plan, classify_task, enforce_request_arguments, extract_request_constraints,
    mark_plan_running, publish_phase, publish_plan, publish_review, sanitize_plan,
    skip_pending, update_plan_from_result,
)
from backend.app.agent.review import combine_reviews, deterministic_review, semantic_review
from backend.app.agent.state import AgentStateV1
from backend.app.agent.verified_answers import render_verified_core_facts
from backend.app.contracts.agent import ModelMessage, ModelToolCall
from backend.app.contracts.common import RequestContext
from backend.app.contracts.workflow import PlanItem, source_refs
from backend.app.ports.executor import EventSink
from backend.app.ports.model import ModelPort
from backend.app.ports.tools import ToolRegistry, ToolResult, ToolSpec
from backend.app.services.model_observation import collect_model_response


def _tool_result_summary(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str, indent=2)


def _safe_args(arguments: dict[str, Any]) -> dict[str, Any]:
    blocked = {"owner_id", "run_id", "api_key", "token", "authorization"}
    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            return value[:300]
        if isinstance(value, list):
            return [scrub(item) for item in value[:20]]
        if isinstance(value, dict):
            return {str(key): scrub(item) for key, item in list(value.items())[:20]
                    if str(key).lower() not in blocked}
        return value
    return {str(key): scrub(value) for key, value in arguments.items() if key.lower() not in blocked}


def _validate_arguments(spec: ToolSpec | None, arguments: dict[str, Any]) -> str | None:
    if spec is None:
        return "UNKNOWN_TOOL"
    schema = spec.input_schema or {}
    missing = [key for key in schema.get("required") or [] if key not in arguments]
    if missing:
        return "missing required argument: " + ", ".join(missing)
    if schema.get("additionalProperties") is False:
        allowed = set((schema.get("properties") or {}).keys())
        extra = [key for key in arguments if key not in allowed]
        if extra:
            return "unknown argument: " + ", ".join(extra)
    return None


def _append_tool_message(state: AgentStateV1, call: ModelToolCall, result: ToolResult) -> None:
    content = json.dumps({"call_id": result.call_id or call.id, "ok": result.ok,
        "data": result.data, "error": result.error, "meta": result.meta},
        ensure_ascii=False, default=str)
    state["messages"].append(ModelMessage(role="tool", content=content,
        tool_call_id=call.id, name=call.name))


def build_graph_v1(
    model: ModelPort,
    registry: ToolRegistry,
    sink: EventSink,
    budget: RunBudget,
    ctx: RequestContext,
    *,
    model_timeout: float = 60.0,
    tool_timeout: float = 15.0,
):
    message_id = "msg_" + ctx.run_id + "_assistant" if ctx.run_id else "msg_assistant"

    async def model_node(state: AgentStateV1) -> dict[str, Any]:
        specs = registry.available(ctx)
        model_messages = list(state.get("messages", []))
        verified_core = render_verified_core_facts(state)
        if verified_core and model_messages and model_messages[0].role == "system":
            model_messages[0] = model_messages[0].model_copy(update={
                "content": model_messages[0].content + "\n\n经来源核验的辅助事实（不得替换你的回答）:\n" + verified_core,
            })
        calls: dict[int, dict[str, str]] = {}
        async def emit_model_event(kind: str, payload: dict[str, Any]) -> None:
            if kind == "token":
                return
            await sink.emit(kind, payload)

        response = await collect_model_response(
            model, model_messages, specs, ctx, budget, emit_model_event,
            purpose="agent_step", timeout_seconds=model_timeout,
        )
        parts: list[str] = []
        for delta in response.deltas:
            if delta.kind == "token" and delta.content:
                parts.append(delta.content)
            elif delta.kind == "tool_call" and delta.tool_call is not None:
                raw = delta.tool_call
                index = raw.index
                if index is None:
                    index = next((key for key, value in calls.items() if raw.id and value["id"] == raw.id), None)
                if index is None:
                    index = next((candidate for candidate in range(len(calls) + 1) if candidate not in calls), 0)
                current = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if raw.id:
                    current["id"] = raw.id
                if raw.name:
                    current["name"] = raw.name
                current["arguments"] += raw.arguments
        usage = response.usage
        model_call_id = response.successful_call_id
        text = "".join(parts)
        tool_calls = [
            ModelToolCall(
                id=value["id"] or f"call_{index + 1}",
                name=value["name"],
                arguments=value["arguments"],
                index=index,
            )
            for index, value in sorted(calls.items())
            if value["name"]
        ]
        state["messages"].append(
            ModelMessage(role="assistant", content=text, tool_calls=tool_calls)
        )
        state["pending_tool_calls"] = tool_calls
        state["usage"] = usage
        if not tool_calls:
            state["final_answer"] = text
        return {
            "messages": state["messages"],
            "pending_tool_calls": tool_calls,
            "usage": usage,
            "model_call_id": model_call_id,
            "final_answer": text if not tool_calls else "",
        }

    async def tools_node(state: AgentStateV1) -> dict[str, Any]:
        pending = list(state.get("pending_tool_calls") or [])
        evidence = list(state.get("evidence") or [])
        tool_error = bool(state.get("tool_error"))
        for call in pending:
            await budget.charge_tool()
            call_id = call.id or "call_" + uuid4().hex
            try:
                arguments = json.loads(call.arguments or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("tool arguments must be a JSON object")
            except ValueError as exc:
                arguments = {}
                error = {"code": "INVALID_ARGUMENTS", "message": str(exc)}
                await sink.emit(
                    "tool_started",
                    {"call_id": call_id, "name": call.name, "actor": ctx.actor,
                     "parent_call_id": state.get("model_call_id"), "args_summary": {}, "simulation": False},
                )
                await sink.emit(
                    "tool_finished",
                    {
                        "call_id": call_id,
                        "status": "error",
                        "result_summary": "",
                        "source": "",
                        "error": "INVALID_ARGUMENTS: " + str(exc),
                        "simulation": False,
                    },
                )
                _append_tool_message(
                    state,
                    call,
                    ToolResult(ok=False, error=error, call_id=call_id),
                )
                tool_error = True
                continue
            spec = next((item for item in registry.available(ctx) if item.name == call.name), None)
            constraints = state.get("request_constraints") or {}
            bounded_arguments, scope_error = enforce_request_arguments(
                call.name, arguments, constraints,
                set((spec.input_schema.get("properties") or {}).keys()) if spec is not None else set(),
            )
            if bounded_arguments is not None:
                arguments = bounded_arguments
            if spec is not None and state.get("plan"):
                state["plan"] = [item.model_dump(mode="json") for item in mark_plan_running(
                    [PlanItem.model_validate(item) for item in state["plan"]], call.name
                )]
                await publish_plan(state, sink)
            validation = scope_error or _validate_arguments(spec, arguments)
            await sink.emit(
                "tool_started",
                {
                    "call_id": call_id,
                    "name": call.name,
                    "actor": ctx.actor,
                    "parent_call_id": state.get("model_call_id"),
                    "args_summary": _safe_args(arguments),
                    "simulation": False,
                },
            )
            if validation is not None:
                result = ToolResult(
                    ok=False,
                    error={"code": "UNKNOWN_TOOL" if spec is None else "INVALID_ARGUMENTS", "message": validation},
                    call_id=call_id,
                )
            else:
                try:
                    operation_timeout = 30.0 if spec is not None and spec.effect == "sandbox_execute" else tool_timeout
                    result = await asyncio.wait_for(
                        registry.invoke(call.name, arguments, replace(ctx, call_id=call_id), budget),
                        timeout=budget.bounded_timeout(operation_timeout),
                    )
                except asyncio.TimeoutError:
                    await budget.check_active()
                    result = ToolResult(
                        ok=False,
                        error={"code": "SANDBOX_TIMEOUT" if spec is not None and spec.effect == "sandbox_execute" else "TOOL_TIMEOUT",
                               "message": f"{call.name} exceeded {operation_timeout:g} seconds"},
                        call_id=call_id,
                    )
                except Exception as exc:  # noqa: BLE001 - 工具失败反馈给模型
                    result = ToolResult(
                        ok=False,
                        error={"code": "TOOL_FAILED", "message": f"{type(exc).__name__}: {exc}"},
                        call_id=call_id,
                    )
            result = ToolResult(
                ok=result.ok,
                data=result.data,
                error=result.error,
                meta=result.meta,
                call_id=call_id,
            )
            if result.ok:
                source = str(result.meta.get("data_source", "local_seed"))
                summary = _tool_result_summary(result.data)
                await sink.emit(
                    "tool_finished",
                    {
                        "call_id": call_id,
                        "status": "success",
                        "result_summary": summary,
                        "source": source,
                        "simulation": False,
                    },
                )
                evidence.extend(collect_evidence(call.name, result, call_id=call_id, arguments=arguments))
                result = ToolResult(ok=True, data=result.data, meta={**result.meta, "tool_name": call.name,
                    "evidence_refs": collect_evidence(call.name, result, call_id=call_id, arguments=arguments)}, call_id=call_id)
            else:
                code = (result.error or {}).get("code", "TOOL_FAILED")
                message = (result.error or {}).get("message", "tool failed")
                await sink.emit(
                    "tool_finished",
                    {
                        "call_id": call_id,
                        "status": "error",
                        "result_summary": "",
                        "source": "",
                        "error": f"{code}: {message}"[:500],
                        "simulation": False,
                    },
                )
                tool_error = True
            if result.meta.get("tool_name") != call.name:
                result = ToolResult(
                    ok=result.ok, data=result.data, error=result.error,
                    meta={**result.meta, "tool_name": call.name}, call_id=call_id,
                )
            if result.ok and isinstance(result.data, dict) and (
                isinstance(result.data.get("total"), int)
                or isinstance(result.data.get("records"), list)
                or isinstance(result.data.get("lines"), list)
            ):
                query_evidence = {
                    "call_id": call_id, "tool_name": call.name,
                    "data_source": str(result.meta.get("data_source", "local_seed")),
                    "arguments": arguments, "as_of": result.meta.get("as_of"),
                    "total": result.data.get("total"),
                    "page": result.data.get("page"),
                    "pages": result.data.get("pages"),
                    "page_size": result.data.get("page_size"),
                    "record_ids": [str(item.get("id")) for item in result.data.get("records", [])
                                   if isinstance(item, dict) and item.get("id")],
                }
                result = ToolResult(
                    ok=True, data=result.data, error=result.error,
                    meta={**result.meta, "query_evidence": query_evidence}, call_id=call_id,
                )
            if state.get("plan"):
                state["plan"] = [item.model_dump(mode="json") for item in update_plan_from_result(
                    [PlanItem.model_validate(item) for item in state["plan"]], result,
                    state.get("request_constraints"),
                )]
                state["evidence_refs"] = [item.model_dump(mode="json") for item in source_refs(evidence)]
                await publish_plan(state, sink)
            _append_tool_message(state, call, result)
            if call.name == "mutation_prepare" and result.ok and isinstance(result.data, dict):
                approval_id = result.data.get("approval_id")
                if isinstance(approval_id, str) and approval_id:
                    state["proposal_interrupt"] = {
                        "interrupt_id": "proposal_" + approval_id,
                        "kind": "mutation_proposal",
                        "proposal_id": result.data.get("proposal_id"),
                        "approval_id": approval_id,
                        "action": result.data.get("action"),
                        "payload": result.data.get("payload"),
                        "fact_snapshot": result.data.get("fact_snapshot") or {},
                        "version": result.data.get("version", 1),
                        "summary": "等待人工确认业务操作提案。",
                    }
                    break
        state["pending_tool_calls"] = []
        state["evidence"] = evidence
        state["tool_error"] = tool_error
        return {
            "pending_tool_calls": [], "evidence": evidence, "tool_error": tool_error,
            "plan": list(state.get("plan") or []),
            "evidence_refs": list(state.get("evidence_refs") or []),
            "proposal_interrupt": state.get("proposal_interrupt"),
        }

    def route(state: AgentStateV1) -> str:
        return "tools" if state.get("pending_tool_calls") else "end"

    builder = StateGraph(AgentStateV1)
    builder.add_node("model", model_node)
    builder.add_node("tools", tools_node)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", route, {"tools": "tools", "end": END})
    builder.add_edge("tools", "model")
    return builder.compile()
