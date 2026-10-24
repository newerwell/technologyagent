"""P04 run 与 Mongo 检查点协调；恢复前核对 owner、interrupt 和草稿版本。"""

from __future__ import annotations

import asyncio
import json
import logging

from langgraph.types import Command

from backend.app.agent.order_nodes import build_order_graph, workflow_config
from backend.app.contracts.agent import ExecutionOutcome
from backend.app.contracts.common import AppError, ErrorCodes, RequestContext
from backend.app.contracts.order_workflow import DraftPrepareRequest, ResumeRequest, WorkflowStartRequest
from backend.app.contracts.agent import ModelMessage
from backend.app.contracts.common import PageQuery
from backend.app.ports.model import ModelPort
from backend.app.ports.tools import ToolSpec
from backend.app.repositories.mongo import MongoResources
from backend.app.services.approvals import ApprovalService
from backend.app.services.drafts import DraftService
from backend.app.services.mutations import MutationService
from backend.app.services.runs import RunService

logger = logging.getLogger(__name__)


class OrderWorkflowService:
    def __init__(self, mongo: MongoResources, runs: RunService, drafts: DraftService,
                 approvals: ApprovalService, mutations: MutationService,
                 model: ModelPort | None = None, catalog=None, model_mode: str = "fake") -> None:
        self._mongo, self._runs, self._drafts = mongo, runs, drafts
        self._approvals, self._mutations = approvals, mutations
        self._model, self._catalog, self._model_mode = model, catalog, model_mode

    async def _live_draft_request(self, message: str, ctx: RequestContext):
        if self._model is None or self._catalog is None:
            raise AppError(ErrorCodes.DEPENDENCY_UNAVAILABLE, "live model is not configured", http_status=503)
        spec = ToolSpec(
            name="order_draft_prepare",
            description="从用户的补货请求提取零件名称、可选仓库和最长交期；不要编造供应商、报价、数量或金额。",
            input_schema={"type": "object", "properties": {
                "part_name": {"type": "string", "minLength": 1},
                "warehouse_id": {"type": "string", "minLength": 1},
                "max_lead_days": {"type": "integer", "minimum": 0},
            }, "required": ["part_name", "max_lead_days"], "additionalProperties": False},
        )
        calls: dict[int, dict[str, str]] = {}

        async def consume():
            async for delta in self._model.stream([
                ModelMessage(role="system", content="你只负责把采购补货请求映射到 order_draft_prepare。按工具schema输出，不猜测仓库；缺少仓库时省略该字段。"),
                ModelMessage(role="user", content=message),
            ], [spec], ctx):
                if delta.kind == "tool_call" and delta.tool_call is not None:
                    call = delta.tool_call
                    index = call.index if call.index is not None else 0
                    value = calls.setdefault(index, {"name": "", "arguments": ""})
                    value["name"] = value["name"] or call.name
                    value["arguments"] += call.arguments

        try:
            async with asyncio.timeout(60):
                await consume()
        except TimeoutError as exc:
            raise AppError(ErrorCodes.DEPENDENCY_UNAVAILABLE, "order intent extraction timed out", http_status=504, retryable=True) from exc
        if len(calls) != 1 or next(iter(calls.values()))["name"] != spec.name:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "model did not return one valid order intent", http_status=422)
        raw_arguments = next(iter(calls.values()))["arguments"]
        try:
            arguments = json.loads(raw_arguments)
        except (TypeError, json.JSONDecodeError) as exc:
            logger.warning("order intent arguments are invalid JSON error=%s", type(exc).__name__)
            raise AppError(ErrorCodes.VALIDATION_ERROR, "model order intent arguments are invalid", http_status=422) from exc
        if not isinstance(arguments, dict):
            logger.warning("order intent arguments must be an object type=%s", type(arguments).__name__)
            raise AppError(ErrorCodes.VALIDATION_ERROR, "model order intent arguments must be an object", http_status=422)
        part_name = arguments.pop("part_name", None)
        if not isinstance(part_name, str) or not part_name.strip():
            logger.warning("order intent part name missing type=%s", type(part_name).__name__)
            raise AppError(ErrorCodes.VALIDATION_ERROR, "model order intent requires a part name", http_status=422)
        try:
            page = await self._catalog.search_parts(part_name.strip(), PageQuery(page=1, page_size=10))
        except Exception as exc:
            logger.warning("order intent catalog lookup failed error=%s", type(exc).__name__)
            raise AppError(ErrorCodes.DEPENDENCY_UNAVAILABLE, "part catalog lookup failed", http_status=503) from exc
        if len(page.records) != 1:
            logger.warning("order intent part lookup count=%s", len(page.records))
            raise AppError(ErrorCodes.VALIDATION_ERROR, "part name is missing or ambiguous", http_status=422)
        try:
            return DraftPrepareRequest(part_ids=[page.records[0].id], **arguments)
        except Exception as exc:
            logger.warning("order intent fields failed validation fields=%s error=%s", sorted(arguments), type(exc).__name__)
            raise AppError(ErrorCodes.VALIDATION_ERROR, "model order intent fields failed schema validation", http_status=422) from exc

    def _graph(self):
        return build_order_graph(self._drafts, self._approvals, self._mutations, self._mongo.checkpointer)

    async def _settle(self, state: dict, run_id: str, ctx: RequestContext):
        pending = state.get("__interrupt__") or []
        if pending:
            payload = pending[0].value
            return await self._runs.wait_for_input(run_id, payload, ctx)
        summary = state.get("summary") or "订单工作流完成。"
        return await self._runs.finish(run_id, ExecutionOutcome(status="completed", summary=summary), ctx)

    async def start(self, request: WorkflowStartRequest, ctx: RequestContext):
        draft_request = (
            await self._live_draft_request(request.message, ctx)
            if self._model_mode == "live"
            else request.draft
        )
        if draft_request is None:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "draft is required in offline mode", http_status=422)
        run, created = await self._runs.create_or_get(
            request.thread_id, request.message, request.request_id, ctx)
        if not created:
            return run
        run_ctx = RequestContext(owner_id=ctx.owner_id, request_id=ctx.request_id, run_id=run.id)
        await self._runs.append_event(run.id, "run_started", {
            "status": "running", "thread_id": run.thread_id, "run_id": run.id, "model_mode": self._model_mode,
        }, run_ctx)
        try:
            state = await self._graph().ainvoke({
                "owner_id": ctx.owner_id, "run_id": run.id, "thread_id": run.thread_id,
                "request": draft_request.model_dump(mode="json"),
            }, config=workflow_config(run.thread_id, run.id))
        except Exception as exc:
            logger.exception("order workflow start failed error=%s", type(exc).__name__)
            await self._runs.finish(run.id, ExecutionOutcome(
                status="failed", summary="订单工作流失败；没有确认成功的结果。",
                error_code="ORDER_WORKFLOW_FAILED",
            ), run_ctx)
            raise AppError(ErrorCodes.DEPENDENCY_UNAVAILABLE,
                           "order workflow failed before reaching a durable decision", http_status=500) from exc
        return await self._settle(state, run.id, run_ctx)

    async def resume(self, run_id: str, request: ResumeRequest, ctx: RequestContext):
        run = await self._runs.get(run_id, ctx)
        pending = run.pending_interrupt
        if run.status != "waiting_input" or pending is None:
            raise AppError(ErrorCodes.RUN_NOT_ACTIVE, "run is not waiting for input", http_status=409)
        if request.interrupt_id != pending.interrupt_id or request.expected_version != pending.version:
            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "interrupt id or draft version is stale", http_status=409)
        if pending.kind == "supplement":
            if request.decision != "supplement":
                raise AppError(ErrorCodes.VALIDATION_ERROR, "supplement decision is required", http_status=422)
            allowed = set(pending.fields or [])
            if not request.payload or set(request.payload) - allowed:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "supplement contains unexpected fields", http_status=422)
            resume_value = request.payload
        else:
            if request.decision not in {"approve", "reject", "edit"}:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "approval decision must be approve, reject, or edit", http_status=422)
            resume_value = {"decision": request.decision, "idempotency_key": request.idempotency_key,
                            "payload": request.payload}
        await self._runs.resume_waiting(run_id, request.interrupt_id, request.expected_version, ctx)
        run_ctx = RequestContext(owner_id=ctx.owner_id, request_id=ctx.request_id, run_id=run_id)
        try:
            state = await self._graph().ainvoke(
                Command(resume=resume_value),
                config=workflow_config(run.thread_id, run_id),
            )
        except Exception as exc:
            logger.exception("order workflow recovery failed error=%s", type(exc).__name__)
            await self._runs.finish(run_id, ExecutionOutcome(
                status="failed", summary="订单恢复失败；请查询审批与操作记录确认状态。",
                error_code="ORDER_WORKFLOW_RECOVERY_FAILED",
            ), run_ctx)
            raise AppError(ErrorCodes.DEPENDENCY_UNAVAILABLE,
                           "order workflow recovery failed", http_status=500) from exc
        return await self._settle(state, run_id, run_ctx)
