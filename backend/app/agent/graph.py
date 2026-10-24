"""P03 单 Agent v1：LangGraph model -> tools -> model，受控只读 registry。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from backend.app.agent.budget import RunBudget, RunCancelled, RunDeadlineExceeded, RunLimitExceeded
from backend.app.agent.evidence import ClaimCheck, collect_evidence, validate_business_claims
from backend.app.agent.state import AgentStateV1
from backend.app.contracts.agent import ExecutionOutcome, ExecutorInput, ModelMessage, ModelToolCall
from backend.app.contracts.common import RequestContext
from backend.app.integrations.model import ModelProviderError
from backend.app.ports.executor import EventSink
from backend.app.ports.model import ModelPort
from backend.app.ports.tools import ToolRegistry, ToolResult, ToolSpec

RegistryFactory = Callable[[RequestContext], Awaitable[ToolRegistry]]

SYSTEM_PROMPT = """你是 TechnologyAgent 的只读采购助手。
只能通过给定工具读取本地业务数据，不得创建、修改或提交订单。
回答库存/报价/补货问题必须基于工具结果，明确数据范围和 as_of；缺失报价不要编造。
结论要简短，只报告回答问题所需的字段；数量使用“缺口X件/在手X件”，交期使用“交期X天”，金额使用“单价X元/总额X元”。
不要把记录编号、版本号、日期时间或无关库存字段当作业务结论重复列出。多个零件分别说明缺口；“库存充足/无需补货”必须写明对应零件。
指定交期上限时，只推荐满足上限的报价；没有有效报价时明确说“没有有效报价”。
如果用户要求下单，明确说明当前只读版本不能执行。
工具失败时说明失败和未完成项，不要声称成功。"""


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
        specs = registry.available(ctx)
        parts: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        usage: dict[str, Any] | None = None

        async def consume() -> None:
            nonlocal usage
            await budget.check_cancelled()
            await budget.check_active()
            async for delta in model.stream(state.get("messages", []), specs, ctx):
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
            await budget.check_active()
            raise GraphExecutionError("MODEL_TIMEOUT", "模型请求超过 60 秒") from exc

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
            claim = validate_business_claims(text, list(state.get("evidence") or []))
            if not claim.passed:
                code = "UNSUPPORTED_OPERATION" if any("read-only" in item for item in claim.violations) else "FACT_CHECK_FAILED"
                raise GraphExecutionError(code, "只读结论校验未通过：" + "; ".join(claim.violations))
            for part in parts:
                await budget.check_cancelled()
                await budget.check_active()
                await sink.emit(
                    "token",
                    {"message_id": message_id, "delta": part, "actor": "main"},
                )
            state["final_answer"] = text
        return {
            "messages": state["messages"],
            "pending_tool_calls": tool_calls,
            "usage": usage,
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
                    {"call_id": call_id, "name": call.name, "actor": "main", "args_summary": {}, "simulation": False},
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
            validation = _validate_arguments(spec, arguments)
            await sink.emit(
                "tool_started",
                {
                    "call_id": call_id,
                    "name": call.name,
                    "actor": "main",
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
                    result = await asyncio.wait_for(
                        registry.invoke(call.name, arguments, ctx, budget),
                        timeout=budget.bounded_timeout(tool_timeout),
                    )
                except asyncio.TimeoutError:
                    await budget.check_active()
                    result = ToolResult(
                        ok=False,
                        error={"code": "TOOL_TIMEOUT", "message": f"{call.name} exceeded 15 seconds"},
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
                summary = json.dumps(result.data, ensure_ascii=False, default=str)[:1500]
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
            _append_tool_message(state, call, result)
        state["pending_tool_calls"] = []
        state["evidence"] = evidence
        state["tool_error"] = tool_error
        return {"pending_tool_calls": [], "evidence": evidence, "tool_error": tool_error}

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
    ) -> None:
        self._model = model
        self._registry_factory = registry_factory
        self.model_mode = model_mode
        self._model_timeout = model_timeout
        self._tool_timeout = tool_timeout

    async def execute(
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
            graph = build_graph_v1(
                self._model,
                registry,
                sink,
                budget,
                request.ctx,
                model_timeout=self._model_timeout,
                tool_timeout=self._tool_timeout,
            )
            initial: AgentStateV1 = {
                "messages": [
                    ModelMessage(role="system", content=SYSTEM_PROMPT),
                    ModelMessage(role="user", content=request.message),
                ],
                "pending_tool_calls": [],
                "final_answer": "",
                "evidence": [],
                "tool_error": False,
                "usage": None,
            }
            try:
                state = await graph.ainvoke(initial, config={"recursion_limit": 80})
            except GraphExecutionError as exc:
                return ExecutionOutcome(
                    status="failed", summary=exc.message, error_code=exc.code
                )
            except (RunCancelled, RunDeadlineExceeded):
                raise
            except ModelProviderError as exc:
                return ExecutionOutcome(
                    status="failed",
                    summary=f"模型调用失败：{exc}",
                    error_code=exc.code,
                )
            except RunLimitExceeded as exc:
                return ExecutionOutcome(
                    status="failed",
                    summary=f"执行预算耗尽：{exc}",
                    error_code="LIMIT_EXCEEDED",
                )
            except asyncio.TimeoutError:
                return ExecutionOutcome(
                    status="failed", summary="执行超时。", error_code="MODEL_TIMEOUT"
                )
            except Exception as exc:  # noqa: BLE001 - 图错误需要可查询终态
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
