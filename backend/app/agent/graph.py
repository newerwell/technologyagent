"""P03 单 Agent v1：LangGraph model -> tools -> model，受控只读 registry。"""

from __future__ import annotations

import asyncio
import json
from time import perf_counter
from dataclasses import replace
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from backend.app.agent.budget import RunBudget, RunCancelled, RunDeadlineExceeded, RunLimitExceeded
from backend.app.agent.evidence import ClaimCheck, collect_evidence, validate_business_claims
from backend.app.agent.harness import (
    MAX_REVISIONS, build_plan, classify_task, enforce_request_arguments, extract_request_constraints, mark_plan_running,
    publish_phase, publish_plan, publish_review, sanitize_plan,
    skip_pending, update_plan_from_result,
)
from backend.app.agent.review import combine_reviews, deterministic_review, semantic_review
from backend.app.agent.verified_answers import render_verified_core_facts
from backend.app.contracts.workflow import PlanItem, source_refs
from backend.app.agent.state import AgentStateV1
from backend.app.contracts.agent import ExecutionOutcome, ExecutorInput, ModelMessage, ModelToolCall
from backend.app.contracts.common import RequestContext
from backend.app.integrations.model import ModelProviderError
from backend.app.ports.executor import EventSink
from backend.app.ports.model import ModelPort
from backend.app.ports.tools import ToolRegistry, ToolResult, ToolSpec

RegistryFactory = Callable[[RequestContext], Awaitable[ToolRegistry]]


def _tool_result_summary(data: Any) -> str:
    """Persist a complete, parseable tool result for audit and deterministic review."""
    return json.dumps(data, ensure_ascii=False, default=str, indent=2)

SYSTEM_PROMPT = """你是 TechnologyAgent 的只读采购助手。
只能通过给定工具读取本地业务数据，不得创建、修改或提交订单。
回答库存/报价/补货问题必须基于工具结果，明确数据范围和 as_of；缺失报价不要编造。
结论要简短，只报告回答问题所需的字段；数量使用“缺口X件/在手X件”，交期使用“交期X天”，金额使用“单价X元/总额X元”。
不要把记录编号、版本号、日期时间或无关库存字段当作业务结论重复列出。多个零件分别说明缺口；“库存充足/无需补货”必须写明对应零件。
指定交期上限时，只推荐满足上限的报价；没有有效报价时明确说“没有有效报价”。
如果用户要求下单，明确说明当前只读版本不能执行。
工具失败时说明失败和未完成项，不要声称成功。"""


def build_specialist_system_prompt(request: ExecutorInput) -> str:
    prompt = SYSTEM_PROMPT
    if request.ctx.actor == "order":
        prompt += (
            "\n\n订单专家可以使用 mutation_prepare 创建待审批提案；业务写入只能由用户批准后执行。"
            "准备提案后必须停止并等待人工批准，不得直接调用业务写工具，也不得把提案描述成已完成写入。"
        )
    if request.ctx.actor == "analyst":
        from backend.app.agent.request_intent import parse_request_intent
        if parse_request_intent(request.message).report_requested:
            prompt += (
                "\n\n用户明确要求生成报告文件。完成相关只读查询后，必须调用 artifact_report，"
                "使用当前run成功查询返回的 dataset_id；不能用文本摘要代替文件。"
                "如果无法生成文件，明确报告失败，不得声称已生成。"
            )
    if request.skill_context:
        prompt += "\n\n本任务技能指引（按版本加载）:\n" + request.skill_context
    if request.request_constraints is not None:
        prompt += "\n\n完整用户请求提取的结构化约束；不得丢弃或自行放宽:\n" + json.dumps(
            request.request_constraints, ensure_ascii=False, sort_keys=True
        )
    return prompt


class GraphExecutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _safe_args(arguments: dict[str, Any]) -> dict[str, Any]:
    blocked = {"owner_id", "run_id", "api_key", "token", "authorization"}

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            return value[:300]
        if isinstance(value, list):
            return [scrub(item) for item in value[:20]]
        if isinstance(value, dict):
            return {
                str(key): scrub(item)
                for key, item in list(value.items())[:20]
                if str(key).lower() not in blocked
            }
        return value

    return {str(key): scrub(value) for key, value in arguments.items() if key.lower() not in blocked}


def _validate_arguments(spec: ToolSpec | None, arguments: dict[str, Any]) -> str | None:
    if spec is None:
        return "UNKNOWN_TOOL"
    schema = spec.input_schema or {}
    required = schema.get("required") or []
    missing = [key for key in required if key not in arguments]
    if missing:
        return "missing required argument: " + ", ".join(missing)
    if schema.get("additionalProperties") is False:
        allowed = set((schema.get("properties") or {}).keys())
        extra = [key for key in arguments if key not in allowed]
        if extra:
            return "unknown argument: " + ", ".join(extra)
    return None


def _append_tool_message(state: AgentStateV1, call: ModelToolCall, result: ToolResult) -> None:
    content = json.dumps(
        {
            "call_id": result.call_id or call.id,
            "ok": result.ok,
            "data": result.data,
            "error": result.error,
            "meta": result.meta,
        },
        ensure_ascii=False,
        default=str,
    )
    state["messages"].append(
        ModelMessage(role="tool", content=content, tool_call_id=call.id, name=call.name)
    )


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
        await budget.charge_model()
        model_call_id = "model_" + uuid4().hex
        model_started = perf_counter()
        await sink.emit("model_started", {"call_id": model_call_id, "actor": ctx.actor,
                                           "purpose": "agent_step"})
        specs = registry.available(ctx)
        model_messages = list(state.get("messages", []))
        verified_core = render_verified_core_facts(state)
        if verified_core and model_messages and model_messages[0].role == "system":
            model_messages[0] = model_messages[0].model_copy(update={
                "content": model_messages[0].content + "\n\n经来源核验的辅助事实（不得替换你的回答）:\n" + verified_core,
            })
        parts: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        usage: dict[str, Any] | None = None

        async def consume() -> None:
            nonlocal usage
            await budget.check_cancelled()
            await budget.check_active()
            async for delta in model.stream(model_messages, specs, ctx):
                await budget.check_cancelled()
                await budget.check_active()
                if delta.kind == "token" and delta.content:
                    parts.append(delta.content)
                elif delta.kind == "tool_call" and delta.tool_call is not None:
                    raw = delta.tool_call
                    index = raw.index
                    if index is None:
                        index = next((key for key, value in calls.items() if raw.id and value["id"] == raw.id), None)
                    if index is None:
                        index = next((candidate for candidate in range(len(calls) + 1) if candidate not in calls), 0)
                    current = calls.setdefault(
                        index, {"id": "", "name": "", "arguments": ""}
                    )
                    if raw.id:
                        current["id"] = raw.id
                    if raw.name:
                        current["name"] = raw.name
                    current["arguments"] += raw.arguments
                elif delta.kind == "usage" and delta.usage:
                    usage = delta.usage

        try:
            await asyncio.wait_for(consume(), timeout=budget.bounded_timeout(model_timeout))
        except asyncio.TimeoutError as exc:
            await sink.emit("model_finished", {"call_id": model_call_id, "status": "error",
                "duration_ms": round((perf_counter() - model_started) * 1000, 3),
                "usage_status": "missing",
                "error_code": "MODEL_TIMEOUT"})
            await budget.check_active()
            raise GraphExecutionError("MODEL_TIMEOUT", "模型请求超过 60 秒") from exc
        except Exception as exc:
            await sink.emit("model_finished", {"call_id": model_call_id, "status": "error",
                "duration_ms": round((perf_counter() - model_started) * 1000, 3),
                "usage_status": "missing",
                "error_code": type(exc).__name__.upper()[:80]})
            raise
        safe_usage = {key: value for key, value in (usage or {}).items()
                      if isinstance(key, str) and key.endswith("_tokens")
                      and isinstance(value, (int, float)) and not isinstance(value, bool)}
        await sink.emit("model_finished", {"call_id": model_call_id, "status": "success",
            "duration_ms": round((perf_counter() - model_started) * 1000, 3),
            "usage": safe_usage or None,
            "usage_status": "reported" if safe_usage else "missing"})

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


class GraphExecutor:
    """P03 AgentExecutor：同一外部 ExecutionOutcome/EventSink 契约。"""

    def __init__(
        self,
        model: ModelPort,
        registry_factory: RegistryFactory,
        *,
        model_mode: str = "live",
        model_timeout: float = 60.0,
        tool_timeout: float = 15.0,
        runs=None,
        order_workflows=None,
        preferences=None,
    ) -> None:
        self._model = model
        self._registry_factory = registry_factory
        self.model_mode = model_mode
        self._model_timeout = model_timeout
        self._tool_timeout = tool_timeout
        self._runs = runs
        self._order_workflows = order_workflows
        self._preferences = preferences

    async def execute(
        self, request: ExecutorInput, sink: EventSink, budget: RunBudget
    ) -> ExecutionOutcome:
        from backend.app.agent.graph_versions import route_executor
        return await route_executor(self, request, sink, budget)

    async def _execute_graph(
        self, request: ExecutorInput, sink: EventSink, budget: RunBudget
    ) -> ExecutionOutcome:
        registry: ToolRegistry | None = None
        try:
            await budget.check_cancelled()
            await budget.check_active()
            try:
                registry = await asyncio.wait_for(
                    self._registry_factory(request.ctx),
                    timeout=budget.bounded_timeout(self._tool_timeout),
                )
            except asyncio.TimeoutError:
                await budget.check_active()
                return ExecutionOutcome(
                    status="failed", summary="只读工具连接准备超过 15 秒。", error_code="TOOL_TIMEOUT"
                )
            if request.graph_version == "v2":
                from backend.app.agent.specialists.policy import RoleToolRegistry, load_specialists
                if request.ctx.actor == "analyst":
                    allowed = load_specialists()["analyst"].tools
                elif request.ctx.actor == "order":
                    allowed = load_specialists()["order"].tools
                else:
                    from mcp_server.tools.specs import READONLY_TOOL_NAMES
                    allowed = READONLY_TOOL_NAMES
                registry = RoleToolRegistry(registry, request.ctx.actor, allowed)
            graph = build_graph_v1(
                self._model,
                registry,
                sink,
                budget,
                request.ctx,
                model_timeout=self._model_timeout,
                tool_timeout=self._tool_timeout,
            )
            task_type = classify_task(request.message)
            initial: AgentStateV1 = {
                "messages": [
                    ModelMessage(role="system", content=build_specialist_system_prompt(request)),
                    ModelMessage(role="user", content=request.message),
                ],
                "pending_tool_calls": [],
                "final_answer": "",
                "evidence": [],
                "tool_error": False,
                "usage": None,
                "task_type": task_type,
                "original_request": request.message,
                "task_summary": request.message,
                "request_constraints": (request.request_constraints if request.request_constraints is not None
                                         else extract_request_constraints(request.message)),
                "plan": [item.model_dump(mode="json") for item in sanitize_plan(build_plan(task_type))],
                "revision_count": 0,
                "evidence_refs": [],
            }
            await publish_phase(initial, "planning", sink)
            await publish_plan(initial, sink, force=True)
            await publish_phase(initial, "executing", sink)
            try:
                state = initial
                final_review = None
                for check_index in range(3):
                    state = await graph.ainvoke(state, config={"recursion_limit": 80})
                    proposal_interrupt = state.get("proposal_interrupt")
                    if proposal_interrupt:
                        waiting = await self._runs.wait_for_input(
                            request.run_id, proposal_interrupt, request.ctx
                        )
                        return ExecutionOutcome(
                            status="waiting_input", summary="等待人工确认业务操作提案。",
                            pending_interrupt=waiting.pending_interrupt.model_dump(mode="json")
                            if waiting.pending_interrupt else proposal_interrupt,
                        )
                    await publish_phase(state, "reviewing", sink)
                    hard = deterministic_review(state)
                    if hard.passed:
                        async def emit_model_event(kind: str, payload: dict[str, Any]) -> None:
                            if request.ctx.run_id:
                                if self._runs is not None:
                                    await self._runs.append_event(request.ctx.run_id, kind, payload, request.ctx)
                                else:
                                    await sink.emit(kind, payload)
                        semantic = await semantic_review(
                            state, self._model, budget, request.ctx, emit=emit_model_event
                        )
                        final_review = combine_reviews(hard, semantic)
                    else:
                        final_review = hard
                    await publish_review(state, final_review, sink)
                    if final_review.passed:
                        break
                    if check_index >= 2 or not final_review.needs_revision:
                        break
                    await publish_phase(state, "executing", sink)
                    reasons = "; ".join(
                        f"{item.check_id}: {item.reason}" for item in final_review.checks if not item.passed
                    )
                    state["messages"].append(ModelMessage(
                        role="user",
                        content=("请修正以下评审发现后重新回答。只允许补充只读查询或改进表述；不得覆盖硬性数值、来源、范围、审批和业务状态。"
                                 "不要重放已完成的业务写入。问题：" + reasons),
                    ))
                    state["final_answer"] = ""
                if final_review is None or not final_review.passed:
                    await publish_phase({**state, "run_status": "failed"}, "result", sink)
                    failed_checks = {item.check_id for item in final_review.checks if not item.passed} if final_review else set()
                    error_code = (
                        "UNSUPPORTED_OPERATION" if "READ_ONLY_BOUNDARY" in failed_checks
                        else "FACT_CHECK_FAILED" if "NUMERIC_MATCH" in failed_checks
                        else "REVIEW_FAILED"
                    )
                    return ExecutionOutcome(status="failed", summary="评审未通过；未完成项：" + ", ".join(
                        final_review.incomplete_items if final_review else ["REVIEW"]
                    ), error_code=error_code)
                if request.ctx.actor == "analyst":
                    from backend.app.agent.request_intent import parse_request_intent
                    if parse_request_intent(request.message).report_requested:
                        if not await self._generate_required_report(registry, request, sink, budget):
                            return ExecutionOutcome(status="failed", summary="报告文件生成或登记失败；订单准备已停止。",
                                                    error_code="REPORT_ARTIFACT_REQUIRED")
                answer = str(state.get("final_answer") or "")
                for part in [answer]:
                    await budget.check_cancelled()
                    await budget.check_active()
                    await sink.emit("token", {"message_id": "msg_" + request.ctx.run_id + "_assistant", "delta": part, "actor": request.ctx.actor})
                await publish_phase(state, "result", sink)
            except GraphExecutionError as exc:
                await publish_phase({"phase": "executing", "run_status": "failed"}, "result", sink)
                return ExecutionOutcome(
                    status="failed", summary=exc.message, error_code=exc.code
                )
            except RunCancelled:
                state = locals().get("state", initial)
                state["plan"] = [item.model_dump(mode="json") for item in skip_pending(
                    [PlanItem.model_validate(item) for item in state.get("plan") or []]
                )]
                await publish_plan(state, sink)
                await publish_phase({**state, "run_status": "cancelled"}, "result", sink)
                raise
            except RunDeadlineExceeded:
                state = locals().get("state", initial)
                state["plan"] = [item.model_dump(mode="json") for item in skip_pending(
                    [PlanItem.model_validate(item) for item in state.get("plan") or []]
                )]
                await publish_plan(state, sink)
                await publish_phase({**state, "run_status": "failed"}, "result", sink)
                raise
            except ModelProviderError as exc:
                await publish_phase({"phase": "executing", "run_status": "failed"}, "result", sink)
                return ExecutionOutcome(
                    status="failed",
                    summary=f"模型调用失败：{exc}",
                    error_code=exc.code,
                )
            except RunLimitExceeded as exc:
                await publish_phase({"phase": "executing", "run_status": "failed"}, "result", sink)
                return ExecutionOutcome(
                    status="failed",
                    summary=f"执行预算耗尽：{exc}",
                    error_code="LIMIT_EXCEEDED",
                )
            except asyncio.TimeoutError:
                await publish_phase({"phase": "executing", "run_status": "failed"}, "result", sink)
                return ExecutionOutcome(
                    status="failed", summary="执行超时。", error_code="MODEL_TIMEOUT"
                )
            except Exception as exc:  # noqa: BLE001 - 图错误需要可查询终态
                await publish_phase({"phase": "executing", "run_status": "failed"}, "result", sink)
                return ExecutionOutcome(
                    status="failed",
                    summary=f"工具循环失败：{type(exc).__name__}",
                    error_code="EXECUTION_FAILED",
                )
            answer = str(state.get("final_answer") or "")
            await budget.check_cancelled()
            await budget.check_active()
            if not answer.strip():
                return ExecutionOutcome(
                    status="failed",
                    summary="模型未生成最终回答。",
                    error_code="EMPTY_ANSWER",
                )
            claim: ClaimCheck = validate_business_claims(
                answer, list(state.get("evidence") or [])
            )
            if not claim.passed:
                return ExecutionOutcome(
                    status="failed",
                    summary="只读版本拒绝执行或缺少依据：" + "; ".join(claim.violations),
                    error_code="UNSUPPORTED_OPERATION",
                )
            final_claim = validate_business_claims(answer, list(state.get("evidence") or []))
            await budget.check_cancelled()
            await budget.check_active()
            return ExecutionOutcome(
                status="completed", summary=answer, evidence=final_claim.cited_facts
            )
        finally:
            close = getattr(registry, "close", None) if registry is not None else None
            if close is not None:
                await close()

    @staticmethod
    def _report_dataset_id(registry, ctx: RequestContext, request_message: str) -> str | None:
        current = registry
        while current is not None:
            getter = getattr(current, "latest_report_dataset_id", None)
            if getter is not None:
                return getter(ctx, request_message)
            current = getattr(current, "_base", None)
        return None

    @staticmethod
    def _registry_method(registry, name: str):
        current = registry
        while current is not None:
            method = getattr(current, name, None)
            if method is not None:
                return method
            current = getattr(current, "_base", None)
        return None

    @staticmethod
    def _event_payload(event):
        if isinstance(event, dict):
            return event.get("type"), event.get("payload", {})
        return getattr(event, "type", None), getattr(event, "payload", {})

    async def _verify_report_artifact(self, registry, request: ExecutorInput,
                                      artifact_id: str, dataset_id: str, report_format: str,
                                      result_data: dict[str, Any]) -> bool:
        if self._runs is None or not hasattr(self._runs, "events"):
            return False
        scope_matches = self._registry_method(registry, "report_dataset_matches_request")
        verify = self._registry_method(registry, "verify_report_artifact")
        if scope_matches is None or verify is None:
            return False
        if not scope_matches(dataset_id, request.ctx, request.message):
            return False
        verification = await verify(artifact_id, dataset_id, report_format, request.ctx)
        if not isinstance(verification, dict):
            return False
        if (verification.get("artifact_id") != artifact_id or verification.get("dataset_id") != dataset_id
                or verification.get("format") != report_format
                or not verification.get("scope") or not verification.get("source_refs")
                or not verification.get("content_sha256")):
            return False
        events = await self._runs.events(request.run_id, 0, request.ctx)
        for event in events:
            event_type, payload = self._event_payload(event)
            if (event_type == "artifact_ready" and payload.get("artifact_id") == artifact_id
                    and payload.get("purpose") == "formal_report"
                    and payload.get("report_dataset_id") == dataset_id
                    and payload.get("report_format") == report_format
                    and payload.get("report_scope") == verification["scope"]
                    and payload.get("content_sha256") == verification["content_sha256"]
                    and payload.get("source_refs") == verification["source_refs"]
                    and result_data.get("source_refs") == verification["source_refs"]):
                await self._runs.append_event(request.run_id, "report_verified", verification, request.ctx)
                return True
        return False

    async def _existing_report_is_verified(self, registry, request: ExecutorInput, report_format: str) -> bool:
        if self._runs is None or not hasattr(self._runs, "events"):
            return False
        events = await self._runs.events(request.run_id, 0, request.ctx)
        starts = {}
        for event in events:
            event_type, payload = self._event_payload(event)
            if event_type == "tool_started" and payload.get("name") == "artifact_report":
                starts[payload.get("call_id")] = payload
        for event in events:
            event_type, payload = self._event_payload(event)
            if event_type != "tool_finished" or payload.get("status") != "success":
                continue
            call = starts.get(payload.get("call_id"))
            if not call:
                continue
            args = call.get("args_summary") or {}
            if args.get("format") != report_format:
                continue
            try:
                result_data = json.loads(payload.get("result_summary") or "{}")
            except (TypeError, ValueError):
                continue
            artifact_id = result_data.get("artifact_id")
            dataset_id = args.get("dataset_id")
            if (isinstance(artifact_id, str) and isinstance(dataset_id, str)
                    and await self._verify_report_artifact(registry, request, artifact_id, dataset_id,
                                                           report_format, result_data)):
                return True
        return False

    async def _generate_required_report(self, registry, request: ExecutorInput,
                                        sink: EventSink, budget: RunBudget) -> bool:
        from backend.app.agent.request_intent import requested_report_format

        report_format = requested_report_format(request.message)
        if await self._existing_report_is_verified(registry, request, report_format):
            return True
        dataset_id = self._report_dataset_id(registry, request.ctx, request.message)
        if not dataset_id:
            return False
        call_id = "call_report_" + uuid4().hex
        await budget.charge_tool()
        await sink.emit("tool_started", {"call_id": call_id, "name": "artifact_report",
            "actor": request.ctx.actor, "parent_call_id": "server_report_requirement",
            "args_summary": {"dataset_id": dataset_id, "format": report_format}, "simulation": False})
        try:
            result = await asyncio.wait_for(
                registry.invoke("artifact_report", {"dataset_id": dataset_id, "format": report_format},
                                replace(request.ctx, call_id=call_id), budget),
                timeout=budget.bounded_timeout(self._tool_timeout),
            )
        except (RunCancelled, RunDeadlineExceeded, RunLimitExceeded):
            raise
        except asyncio.TimeoutError as exc:
            await budget.check_cancelled()
            await budget.check_active()
            await sink.emit("tool_finished", {"call_id": call_id, "status": "error",
                "result_summary": "", "source": "", "error": f"REPORT_GENERATION_FAILED: {type(exc).__name__}"})
            return False
        except Exception as exc:
            await sink.emit("tool_finished", {"call_id": call_id, "status": "error",
                "result_summary": "", "source": "", "error": f"REPORT_GENERATION_FAILED: {type(exc).__name__}"})
            return False
        if not result.ok or not (result.data or {}).get("artifact_id"):
            await sink.emit("tool_finished", {"call_id": call_id, "status": "error",
                "result_summary": "", "source": "", "error": "REPORT_GENERATION_FAILED"})
            return False
        await sink.emit("tool_finished", {"call_id": call_id, "status": "success",
            "result_summary": json.dumps(result.data, ensure_ascii=False),
            "source": "registered_artifact", "simulation": False})
        return await self._verify_report_artifact(registry, request, str(result.data["artifact_id"]),
            dataset_id, report_format, result.data)
