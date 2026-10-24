"""P04 run 与 Mongo 检查点协调；恢复前核对 owner、interrupt 和草稿版本。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

from langgraph.types import Command

from backend.app.agent.order_nodes import build_order_graph, workflow_config
from backend.app.agent.budget import RunBudget, RunCancelled, RunDeadlineExceeded, RunLimitExceeded
from backend.app.agent.review import combine_reviews, semantic_review
from backend.app.contracts.agent import ExecutionOutcome
from backend.app.contracts.common import AppError, ErrorCodes, RequestContext
from backend.app.contracts.order_workflow import DraftPatch, DraftPrepareRequest, ResumeRequest, WorkflowStartRequest
from backend.app.contracts.agent import ModelMessage
from backend.app.contracts.workflow import PlanItem, ReviewCheck, ReviewResult, SourceRef
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

    async def _live_draft_request(self, message: str, ctx: RequestContext, budget: RunBudget):
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
            await budget.charge_model()
            await budget.check_cancelled()
            async def consume_guarded():
                task = asyncio.create_task(consume())
                try:
                    while not task.done():
                        await asyncio.wait({task}, timeout=min(0.1, budget.bounded_timeout(60)))
                        await budget.check_cancelled()
                        await budget.check_active()
                    await task
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
            async with asyncio.timeout(budget.bounded_timeout(60)):
                await consume_guarded()
            await budget.check_cancelled()
            await budget.check_active()
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
            request = DraftPrepareRequest(part_ids=[page.records[0].id], **arguments)
            await self._drafts.validate_prepare(request, ctx)
            return request
        except Exception as exc:
            logger.warning("order intent fields failed validation fields=%s error=%s", sorted(arguments), type(exc).__name__)
            raise AppError(ErrorCodes.VALIDATION_ERROR, "model order intent fields failed schema validation", http_status=422) from exc

    def _graph(self):
        return build_order_graph(self._drafts, self._approvals, self._mutations, self._mongo.checkpointer, self._runs)

    async def _settle(self, state: dict, run_id: str, ctx: RequestContext):
        pending = state.get("__interrupt__") or []
        drafts = state.get("drafts") or []
        order_results = state.get("order_results") or []
        plan = [
            PlanItem(id="prepare_draft", title="准备并校验订单草稿", status="done" if drafts else "pending",
                     evidence_refs=[SourceRef(call_id="order_workflow", entity="drafts", id=str(item["id"])) for item in drafts]),
            PlanItem(id="human_approval", title="等待人工审批", status="running" if pending else "done" if order_results or state.get("rejected_drafts") else "pending"),
            PlanItem(id="verify_order", title="查询订单与审批结果", status="pending" if pending else "done" if order_results else "skipped",
                     evidence_refs=[SourceRef(call_id="order_workflow", entity="orders", id=str(item.get("order", {}).get("id")))
                                    for item in order_results if item.get("order", {}).get("id")]),
        ]
        await self._runs.append_event(run_id, "plan", {
            "task_type": "order", "items": [item.model_dump(mode="json") for item in plan],
            "evidence_refs": [ref.model_dump(mode="json") for item in plan for ref in item.evidence_refs],
        }, ctx)
        if pending:
            payload = pending[0].value
            return await self._runs.wait_for_input(run_id, payload, ctx)
        summary = state.get("summary") or "订单工作流完成。"
        await self._runs.append_event(run_id, "phase", {
            "phase": "reviewing", "task_type": "order", "iteration": 0, "revision_count": 0,
        }, ctx)
        checks: list[ReviewCheck] = []
        verified_orders: list[dict[str, Any]] = []
        for result in order_results:
            operation_id = str(result.get("operation_id") or "")
            order_id = str((result.get("order") or {}).get("id") or "")
            operation = await self._mongo.db["operations"].find_one({
                "_id": operation_id, "owner_id": ctx.owner_id, "action": "order_create", "status": "succeeded",
            }) if operation_id else None
            order = await self._mongo.db["orders"].find_one({
                "_id": order_id, "owner_id": ctx.owner_id, "operation_id": operation_id,
            }) if operation_id and order_id else None
            approval = await self._mongo.db["approvals"].find_one({
                "owner_id": ctx.owner_id, "status": "consumed", "order_id": order_id,
            }) if order_id else None
            order_ok = bool(operation and order and operation.get("order_id") == order_id)
            approval_ok = bool(approval and approval.get("status") == "consumed")
            verified_orders.append({
                "order": order or {},
                "operation": operation or {},
                "approval": approval or {},
            })
            checks.extend([
                ReviewCheck(check_id="ORDER_EXISTS", passed=order_ok,
                            reason="持久订单与成功operation一致。" if order_ok else "未找到匹配的持久订单与成功operation。",
                            evidence_refs=[operation_id] if operation_id else []),
                ReviewCheck(check_id="APPROVAL_EXISTS", passed=approval_ok,
                            reason="订单关联已消费审批。" if approval_ok else "未找到对应的已消费审批。",
                            evidence_refs=[str((approval or {}).get("_id", ""))] if approval else []),
            ])
        hard = ReviewResult(passed=all(item.passed for item in checks), checks=checks,
                            needs_revision=False, revision_count=0,
                            incomplete_items=[item.check_id for item in checks if not item.passed])
        if self._model is not None:
            budget = RunBudget(run_id, model_counter=lambda: self._runs.charge_model(run_id, ctx),
                               cancel_check=lambda: self._runs.cancel_requested(run_id, ctx))
            semantic = await semantic_review({
                "task_type": "order", "task_summary": summary, "final_answer": summary,
                "plan": [item.model_dump(mode="json") for item in plan],
                "evidence_refs": [ref.model_dump(mode="json") for item in plan for ref in item.evidence_refs],
                "verified_orders": {"orders": verified_orders},
                "workflow_outcome": {
                    "submitted_orders": len(order_results),
                    "rejected_drafts": len(state.get("rejected_drafts") or []),
                    "pending_drafts": len(pending),
                },
            }, self._model, budget, ctx)
        else:
            semantic = ReviewResult(passed=True, checks=[ReviewCheck(
                check_id="SEMANTIC_COMPLETE", passed=True, kind="semantic",
                reason="fake模式不调用真实语义评审模型。",
            )], needs_revision=False, revision_count=0)
        review = combine_reviews(hard, semantic)
        await self._runs.append_event(run_id, "review", {
            "passed": review.passed, "checks": [item.check_id for item in review.checks],
            "details": [item.model_dump(mode="json") for item in review.checks],
            "result": review.model_dump(mode="json"), "revision_count": 0,
            "incomplete_items": review.incomplete_items,
        }, ctx)
        await self._runs.append_event(run_id, "phase", {
            "phase": "result", "task_type": "order", "iteration": 0, "revision_count": 0,
        }, ctx)
        if not review.passed:
            return await self._runs.finish(run_id, ExecutionOutcome(
                status="failed", summary="订单事实检查未通过；已完成写入只读核查，不会自动重放。",
                error_code="REVIEW_FAILED", committed_facts=bool(order_results),
            ), ctx)
        return await self._runs.finish(run_id, ExecutionOutcome(
            status="completed", summary=summary,
            committed_facts=bool(state.get("order_results") or state.get("result")),
        ), ctx)

    async def start(self, request: WorkflowStartRequest, ctx: RequestContext):
        if self._model_mode != "live" and request.draft is None:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "draft is required in offline mode", http_status=422)
        run, created = await self._runs.create_or_get(
            request.thread_id, request.message, request.request_id, ctx,
            request_payload={"workflow": request.model_dump(mode="json"), "model_mode": self._model_mode})
        if not created:
            return run
        run_ctx = RequestContext(owner_id=ctx.owner_id, request_id=ctx.request_id, run_id=run.id)
        budget = RunBudget(
            run.id, model_counter=lambda: self._runs.charge_model(run.id, run_ctx),
            cancel_check=lambda: self._runs.cancel_requested(run.id, run_ctx),
        )
        await self._runs.append_event(run.id, "run_started", {
            "status": "running", "thread_id": run.thread_id, "run_id": run.id, "model_mode": self._model_mode,
        }, run_ctx)
        await self._runs.append_event(run.id, "phase", {
            "phase": "planning", "task_type": "order", "iteration": 0, "revision_count": 0,
        }, run_ctx)
        await self._runs.append_event(run.id, "plan", {
            "task_type": "order", "items": [item.model_dump(mode="json") for item in [
                PlanItem(id="prepare_draft", title="准备并校验订单草稿"),
                PlanItem(id="human_approval", title="等待人工审批"),
                PlanItem(id="verify_order", title="查询订单与审批结果"),
            ]], "evidence_refs": [],
        }, run_ctx)
        await self._runs.append_event(run.id, "phase", {
            "phase": "executing", "task_type": "order", "iteration": 0, "revision_count": 0,
        }, run_ctx)
        try:
            draft_request = (
                await self._live_draft_request(request.message, run_ctx, budget)
                if self._model_mode == "live"
                else request.draft
            )
            if draft_request is None:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "draft is required", http_status=422)
            await self._runs.persist_order_intent(run.id, draft_request.model_dump(mode="json"), run_ctx)
            state = await self._graph().ainvoke({
                "owner_id": ctx.owner_id, "run_id": run.id, "thread_id": run.thread_id,
                "request": draft_request.model_dump(mode="json"),
            }, config=workflow_config(run.thread_id, run.id))
        except Exception as exc:
            logger.exception("order workflow start failed error=%s", type(exc).__name__)
            cancelled = isinstance(exc, RunCancelled) or await self._runs.cancel_requested(run.id, run_ctx)
            await self._runs.finish(run.id, ExecutionOutcome(
                status="cancelled" if cancelled else "failed",
                summary="订单流程已取消；未创建订单。" if cancelled else "订单工作流失败；没有确认成功的结果。",
                error_code="RUN_CANCELLED" if cancelled else "ORDER_WORKFLOW_FAILED",
            ), run_ctx)
            if cancelled:
                return await self._runs.get(run.id, run_ctx)
            raise AppError(ErrorCodes.DEPENDENCY_UNAVAILABLE,
                           "order workflow failed before reaching a durable decision", http_status=500) from exc
        return await self._settle(state, run.id, run_ctx)

    async def resume(self, run_id: str, request: ResumeRequest, ctx: RequestContext):
        run = await self._runs.get(run_id, ctx)
        pending = run.pending_interrupt
        request_payload = request.model_dump(mode="json")
        request_hash = hashlib.sha256(json.dumps(
            request_payload, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        persisted = await self._mongo.db["runs"].find_one({"_id": run_id, "owner_id": ctx.owner_id})
        previous = (persisted or {}).get("resume_request") or {}
        if previous.get("idempotency_key") == request.idempotency_key:
            if previous.get("request_hash") != request_hash:
                raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "decision key payload differs", http_status=409)
            return run
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
            stored_workflow = (persisted or {}).get("request_payload", {}).get("workflow", {})
            original_draft = (persisted or {}).get("order_intent") or stored_workflow.get("draft") or {}
            try:
                supplemented = DraftPrepareRequest.model_validate({**original_draft, **request.payload})
            except Exception as exc:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "supplement fields are invalid", http_status=422) from exc
            await self._drafts.validate_prepare(supplemented, ctx)
            resume_value = request.payload
        else:
            if request.decision not in {"approve", "reject", "edit"}:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "approval decision must be approve, reject, or edit", http_status=422)
            resume_value = {"decision": request.decision, "idempotency_key": request.idempotency_key,
                            "payload": request.payload}
            if request.decision == "edit":
                try:
                    edit_patch = DraftPatch.model_validate({
                        "expected_version": request.expected_version,
                        "items": request.payload.get("items"),
                        "supplier_id": request.payload.get("supplier_id"),
                        "warehouse_id": request.payload.get("warehouse_id"),
                    })
                except Exception as exc:
                    raise AppError(ErrorCodes.VALIDATION_ERROR, "edited order fields are invalid", http_status=422) from exc
                await self._drafts.validate_patch(pending.draft_id or "", edit_patch, ctx)
        resume_record = {**request_payload, "request_hash": request_hash}
        resumed, claimed = await self._runs.resume_waiting(
            run_id, request.interrupt_id, request.expected_version, ctx, resume_record
        )
        if not claimed:
            return resumed
        run_ctx = RequestContext(owner_id=ctx.owner_id, request_id=ctx.request_id, run_id=run_id)
        try:
            state = await self._graph().ainvoke(
                Command(resume=resume_value),
                config=workflow_config(run.thread_id, run_id),
            )
        except Exception as exc:
            logger.exception("order workflow recovery failed error=%s", type(exc).__name__)
            cancelled = isinstance(exc, RunCancelled) or await self._runs.cancel_requested(run_id, run_ctx)
            if cancelled:
                await self._runs.finish(run_id, ExecutionOutcome(
                    status="cancelled", summary="订单流程已取消；未提交的订单不会创建。",
                    error_code="RUN_CANCELLED",
                ), run_ctx)
                return await self._runs.get(run_id, run_ctx)
            try:
                persisted_run = await self._mongo.db["runs"].find_one({"_id": run_id, "owner_id": ctx.owner_id})
                if persisted_run and persisted_run.get("resume_request"):
                    recovered = await self._recover_one(persisted_run)
                    if recovered.status in {"completed", "failed", "cancelled", "waiting_input"}:
                        return recovered
                    operation = await self._mongo.db["operations"].find_one({
                        "owner_id": ctx.owner_id, "action": "order_create",
                        "idempotency_key": request.idempotency_key,
                    })
                    if operation and operation.get("status") == "succeeded":
                        return recovered
            except Exception as recovery_error:
                logger.warning("immediate order recovery deferred error=%s", type(recovery_error).__name__)
            await self._runs.finish(run_id, ExecutionOutcome(
                status="failed",
                summary="订单恢复失败；请查询审批与操作记录确认状态。",
                error_code="ORDER_WORKFLOW_RECOVERY_FAILED",
                committed_facts=bool(getattr(exc, "committed_order", False)),
            ), run_ctx)
            raise AppError(ErrorCodes.DEPENDENCY_UNAVAILABLE,
                           "order workflow recovery failed", http_status=500) from exc
        return await self._settle(state, run_id, run_ctx)

    async def _recover_one(self, document: dict):
        run_id = document["_id"]
        ctx = RequestContext(owner_id=document["owner_id"], request_id="workflow-recovery", run_id=run_id)
        config = workflow_config(document["thread_id"], run_id)
        graph = self._graph()
        request = document["resume_request"]
        decision = request.get("decision")
        payload = request.get("payload") or {}
        value = payload if decision == "supplement" else {
            "decision": decision, "idempotency_key": request.get("idempotency_key"),
            "payload": payload,
        }
        try:
            state = await graph.ainvoke(Command(resume=value), config=config)
        except ValueError as exc:
            # A checkpoint may already have consumed the interrupt and reached END
            # before run._settle was saved. In that case continue from the checkpoint.
            if "interrupt" not in str(exc).lower():
                raise
            state = await graph.ainvoke(None, config=config)
        return await self._settle(state, run_id, ctx)

    async def recover_pending(self) -> int:
        """Resume durable decisions from their Mongo checkpoint after a process restart."""
        documents = await self._mongo.db["runs"].find({
            "status": "running", "resume_request": {"$exists": True},
        }).to_list(length=None)
        recovered = 0
        for document in documents:
            try:
                await self._recover_one(document)
                recovered += 1
            except Exception as exc:
                logger.exception("order workflow durable recovery failed error=%s", type(exc).__name__)
        return recovered
