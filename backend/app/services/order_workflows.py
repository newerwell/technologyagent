"""P04 run 与 Mongo 检查点协调；恢复前核对 owner、interrupt 和草稿版本。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any

from langgraph.types import Command

from backend.app.agent.fact_checks import build_fact_index, validate_answer
from backend.app.agent.order_nodes import build_order_graph, workflow_config
from backend.app.agent.budget import RunBudget, RunCancelled, RunDeadlineExceeded, RunLimitExceeded
from backend.app.agent.review import combine_reviews, semantic_review
from backend.app.services.model_observation import observed_model_stream
from backend.app.contracts.agent import ExecutionOutcome
from backend.app.contracts.common import AppError, ErrorCodes, RequestContext
from backend.app.contracts.order_workflow import DraftPatch, DraftPrepareRequest, ResumeRequest, WorkflowStartRequest
from backend.app.contracts.events import RunView
from backend.app.contracts.agent import ModelMessage
from backend.app.contracts.workflow import PlanItem, ReviewCheck, ReviewResult, SourceRef
from backend.app.contracts.common import PageQuery
from backend.app.ports.model import ModelPort
from backend.app.ports.tools import ToolSpec
from backend.app.repositories.mongo import MongoResources
from backend.app.services.approvals import ApprovalService
from backend.app.integrations.business_provider import ensure_local_capability
from backend.app.services.drafts import DraftService
from backend.app.services.mutations import MutationService
from backend.app.services.runs import RunService
from backend.app.agent.skill_loader import render_skill_context, select_skills

logger = logging.getLogger(__name__)


def _order_answer_fact_check(answer: str, verified_orders: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Check explicit quantity/money claims against persisted order facts."""
    facts: list[dict[str, Any]] = []
    for item in verified_orders:
        order = item.get("order") or {}
        order_id = str(order.get("number") or order.get("_id") or order.get("id") or "")
        persisted_id = str(order.get("_id") or order.get("id") or order_id)
        warehouse_id = order.get("warehouse_id")
        supplier_id = order.get("supplier_id")
        lines = [line for line in order.get("items", []) if isinstance(line, dict)]
        order_parts = {str(line.get("part_id")) for line in lines if line.get("part_id")}
        order_source = [{"entity": "order", "id": persisted_id}]
        common = {
            "call_id": str(item.get("operation_id") or "persisted-order"),
            "entity": "order", "entity_id": order_id, "id": persisted_id,
            "order_id": order_id, "warehouse_id": warehouse_id,
            "supplier_id": supplier_id, "source_refs": order_source,
        }
        if len(order_parts) == 1:
            common["part_id"] = next(iter(order_parts))
        total = order.get("total_cents")
        if isinstance(total, int) and not isinstance(total, bool):
            root_fact = {**common, "field": "order_total_cents", "value": total, "unit": "cents"}
            facts.append(root_fact)
            # The shorter label "总额" means the persisted order total here.
            facts.append({**root_fact, "field": "total_cents"})
        for line_index, line in enumerate(lines):
            scope = {
                **common,
                "entity": "order_line", "entity_id": f"{persisted_id}:{line_index}",
                "record_id": f"{persisted_id}:{line_index}",
                "part_id": line.get("part_id"),
            }
            business_unit = line.get("unit") or line.get("business_unit")
            if len(order_parts) == 1:
                scope["part_id"] = next(iter(order_parts))
            for field, unit in (
                ("quantity", business_unit or "count"),
                ("unit_price_cents", "cents"),
                ("line_total_cents", "cents"),
            ):
                value = line.get(field)
                if isinstance(value, int) and not isinstance(value, bool):
                    facts.append({**scope, "field": field, "value": value, "unit": unit})
    checked = validate_answer(answer, build_fact_index(facts))
    return checked.passed, list(checked.violations)


class OrderWorkflowService:
    def __init__(self, mongo: MongoResources, runs: RunService, drafts: DraftService,
                 approvals: ApprovalService, mutations: MutationService,
                 model: ModelPort | None = None, catalog=None, model_mode: str = "fake", preferences=None) -> None:
        self._mongo, self._runs, self._drafts = mongo, runs, drafts
        self._approvals, self._mutations = approvals, mutations
        self._model, self._catalog, self._model_mode = model, catalog, model_mode
        self._preferences = preferences
        self._providers: dict[str, object] | None = None

    def set_providers(self, providers: dict[str, object]) -> None:
        self._providers = providers

    def _ensure_order_write_provider(self) -> None:
        if self._providers is None:
            raise AppError(ErrorCodes.DEPENDENCY_UNAVAILABLE,
                           "business write provider is not configured", http_status=503)
        for module in ("orders", "inventory", "parts", "suppliers"):
            ensure_local_capability(self._providers, module, write=True)

    async def _live_draft_request(self, message: str, ctx: RequestContext, budget: RunBudget,
                                  evidence_refs: list[dict[str, Any]] | None = None,
                                  skill_context: str = "", request_constraints: dict[str, Any] | None = None):
        if self._model is None or self._catalog is None:
            raise AppError(ErrorCodes.DEPENDENCY_UNAVAILABLE, "live model is not configured", http_status=503)
        spec = ToolSpec(
            name="order_draft_prepare",
            description="从用户的补货请求提取全部零件ID或名称、可选仓库、供应商和最长交期；不要遗漏明确物料，不要编造报价、数量或金额。",
            input_schema={"type": "object", "properties": {
                "part_id": {"type": "string", "pattern": "^P[0-9]{3}$"},
                "part_ids": {"type": "array", "items": {"type": "string", "pattern": "^P[0-9]{3}$"}, "minItems": 1, "maxItems": 50},
                "part_name": {"type": "string", "minLength": 1},
                "warehouse_id": {"type": "string", "minLength": 1},
                "supplier_id": {"type": "string", "pattern": "^S[0-9]{2,3}$"},
                "max_lead_days": {"type": "integer", "minimum": 0},
            }, "required": ["max_lead_days"], "additionalProperties": False},
        )
        calls: dict[int, dict[str, str]] = {}

        async def consume():
            messages = [
                ModelMessage(role="system", content="你只负责把采购补货请求映射到 order_draft_prepare。按工具schema输出；保留原请求中的全部物料ID，多个物料必须全部放入part_ids；不要把零件ID当part_name。不要猜测仓库或供应商；缺少时省略。"
                             + ("\n\n订单技能指引:\n" + skill_context if skill_context else "")),
                ModelMessage(role="user", content=json.dumps({
                    "original_request": message,
                    "analyst_evidence_refs": evidence_refs or [],
                    "instruction": "证据仅用于理解任务；订单范围和金额必须由订单服务重新读取和校验。",
                }, ensure_ascii=False, default=str)),
            ]
            async def emit_model_event(kind: str, payload: dict[str, Any]) -> None:
                if ctx.run_id:
                    await self._runs.append_event(ctx.run_id, kind, payload, ctx)
            async for delta in observed_model_stream(
                self._model, messages, [spec], ctx, emit_model_event, purpose="order_intent_extract"
            ):
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
        requested_part_id = arguments.pop("part_id", None)
        requested_part_ids = arguments.pop("part_ids", None)
        requested_ids = {value.upper() for value in re.findall(r"(?<![A-Za-z0-9])(P\d{3})(?![A-Za-z0-9])", message, re.IGNORECASE)}
        model_ids = {str(value).upper() for value in requested_part_ids or []}
        if requested_part_id:
            model_ids.add(str(requested_part_id).upper())
        if requested_ids:
            selected_ids = requested_ids
            if model_ids and model_ids != requested_ids:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "model omitted or added an explicitly requested part", http_status=422)
            if len(requested_ids) > 1 and not model_ids:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "multiple requested parts must all be preserved", http_status=422)
            # A direct user ID is not an analyst authorization token. Resolve it
            # again through the trusted catalog before draft preparation.
            for part_id in selected_ids:
                part = await self._catalog.get_part(part_id)
                if not part.active:
                    raise AppError(ErrorCodes.VALIDATION_ERROR, "requested part is inactive", http_status=422)
        elif model_ids:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "model added a part that the user did not request", http_status=422)
        elif not isinstance(part_name, str) or not part_name.strip():
            raise AppError(ErrorCodes.VALIDATION_ERROR, "model order intent requires a verified part", http_status=422)
        else:
            try:
                page = await self._catalog.search_parts(part_name.strip(), PageQuery(page=1, page_size=10))
            except Exception as exc:
                logger.warning("order intent catalog lookup failed error=%s", type(exc).__name__)
                raise AppError(ErrorCodes.DEPENDENCY_UNAVAILABLE, "part catalog lookup failed", http_status=503) from exc
            if len(page.records) != 1:
                logger.warning("order intent part lookup count=%s", len(page.records))
                raise AppError(ErrorCodes.VALIDATION_ERROR, "part name is missing or ambiguous", http_status=422)
            selected_ids = {page.records[0].id}
        explicit_supplier = re.search(r"(?<![A-Za-z0-9])(S\d{2,3})(?![A-Za-z0-9])", message, re.IGNORECASE)
        if explicit_supplier and not re.search(rf"(?:不用|不要|不考虑)\s*{explicit_supplier.group(1)}", message, re.I):
            arguments["supplier_id"] = explicit_supplier.group(1).upper()
        if request_constraints:
            if request_constraints.get("supplier_id"):
                arguments["supplier_id"] = request_constraints["supplier_id"]
            elif request_constraints.get("clear_preferred_supplier"):
                arguments.pop("supplier_id", None)
            warehouses = request_constraints.get("warehouse_ids") or []
            if warehouses:
                arguments["warehouse_id"] = warehouses[0]
            if request_constraints.get("max_lead_days") is not None:
                arguments["max_lead_days"] = request_constraints["max_lead_days"]
            elif request_constraints.get("clear_max_lead_days"):
                arguments.pop("max_lead_days", None)
        try:
            request = DraftPrepareRequest(part_ids=sorted(selected_ids), **arguments)
            await self._drafts.validate_prepare(request, ctx)
            return request
        except Exception as exc:
            logger.warning("order intent fields failed validation fields=%s error=%s", sorted(arguments), type(exc).__name__)
            raise AppError(ErrorCodes.VALIDATION_ERROR, "model order intent fields failed schema validation", http_status=422) from exc

    def _graph(self, version: str = "v1"):
        return build_order_graph(self._drafts, self._approvals, self._mutations,
                                 self._mongo.checkpointer, self._runs, version=version)

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
        run_document = await self._mongo.db["runs"].find_one({"_id": run_id, "owner_id": ctx.owner_id}) or {}
        user_request = str(state.get("user_request") or run_document.get("message") or "")
        candidate_answer = str(state.get("candidate_answer") or state.get("summary") or "订单工作流完成。")
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
            if order:
                order = dict(order)
                order["items"] = [dict(line) for line in order.get("items", [])]
                if self._catalog is not None:
                    for line in order["items"]:
                        try:
                            line["unit"] = (await self._catalog.get_part(str(line.get("part_id")))).unit
                        except Exception:
                            # Missing catalog facts leave unit-bearing quantity claims unverifiable.
                            pass
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
                            needs_revision=False,
                            incomplete_items=[item.check_id for item in checks if not item.passed])
        budget = RunBudget(
            run_id,
            max_active_seconds=180.0,
            initial_active_seconds=(float(run_document.get("active_seconds_used", 0.0)) +
                                    max(0.0, (self._runs._clock.now() - run_document["active_started_at"]).total_seconds())
                                    if run_document.get("active_started_at") else
                                    float(run_document.get("active_seconds_used", 0.0))),
            max_model_calls=max(0, 20 - int(run_document.get("model_calls", 0))),
            model_counter=lambda: self._runs.charge_model(run_id, ctx),
            cancel_check=lambda: self._runs.cancel_requested(run_id, ctx),
        )
        review: ReviewResult | None = None
        revision_count = min(2, int(run_document.get("revision_count", state.get("revision_count", 0))))
        for review_index in range(3):
            answer_facts_ok, answer_fact_errors = _order_answer_fact_check(candidate_answer, verified_orders)
            answer_fact_check = ReviewCheck(
                check_id="ORDER_FACTS_MATCH", passed=answer_facts_ok,
                reason="正文数量与金额均匹配持久订单。" if answer_facts_ok else "; ".join(answer_fact_errors),
                evidence_refs=[str((item.get("order") or {}).get("_id", "")) for item in verified_orders],
            )
            current_hard = ReviewResult(
                passed=hard.passed and answer_facts_ok,
                checks=[*hard.checks, answer_fact_check],
                needs_revision=hard.passed and not answer_facts_ok,
                incomplete_items=[*hard.incomplete_items, *([] if answer_facts_ok else ["ORDER_FACTS_MATCH"])],
                revision_count=revision_count,
            )
            review_state = {
                "task_type": "order", "task_summary": user_request,
                "final_answer": candidate_answer,
                "plan": [item.model_dump(mode="json") for item in plan],
                "evidence_refs": [ref.model_dump(mode="json") for item in plan for ref in item.evidence_refs],
                "verified_orders": {"orders": verified_orders},
                "workflow_outcome": {
                    "submitted_orders": len(order_results),
                    "rejected_drafts": len(state.get("rejected_drafts") or []),
                    "pending_drafts": len(pending),
                },
                "revision_count": revision_count,
            }
            await self._runs.append_event(run_id, "phase", {
                "phase": "reviewing", "task_type": "order", "iteration": revision_count,
                "revision_count": revision_count,
            }, ctx)
            if not current_hard.passed:
                review = current_hard
            elif self._model is not None:
                async def emit_model_event(kind: str, payload: dict[str, Any]) -> None:
                    await self._runs.append_event(run_id, kind, payload, ctx)
                semantic = await semantic_review(
                    review_state, self._model, budget, ctx, emit=emit_model_event
                )
                review = combine_reviews(current_hard, semantic).model_copy(update={"revision_count": revision_count})
            else:
                review = combine_reviews(current_hard, ReviewResult(passed=True, checks=[ReviewCheck(
                    check_id="SEMANTIC_COMPLETE", passed=True, kind="semantic",
                    reason="fake模式不调用真实语义评审模型。",
                )])).model_copy(update={"revision_count": revision_count})
            await self._runs.append_event(run_id, "review", {
                "passed": review.passed, "checks": [item.check_id for item in review.checks],
                "details": [item.model_dump(mode="json") for item in review.checks],
                "result": review.model_dump(mode="json"), "revision_count": revision_count,
                "incomplete_items": review.incomplete_items,
            }, ctx)
            if review.passed or not review.needs_revision or revision_count >= 2:
                break
            revision_count += 1
            await self._runs.append_event(run_id, "phase", {
                "phase": "executing", "task_type": "order", "iteration": revision_count,
                "revision_count": revision_count,
            }, ctx)
            candidate_answer = await self._revise_order_answer(
                user_request, candidate_answer, verified_orders, review, budget, ctx
            )
        assert review is not None
        await self._runs.append_event(run_id, "phase", {
            "phase": "result", "task_type": "order", "iteration": revision_count,
            "revision_count": revision_count,
        }, ctx)
        if not review.passed:
            submitted = [str(item.get("order", {}).get("number")) for item in order_results
                         if item.get("order", {}).get("number")]
            return await self._runs.finish(run_id, ExecutionOutcome(
                status="failed",
                summary=(f"订单已提交（{', '.join(submitted)}），但说明评审未通过："
                         f"{', '.join(review.incomplete_items)}。不会自动重放订单提交。"
                         if order_results else "订单评审未通过；未确认有订单提交。"),
                error_code="REVIEW_FAILED", committed_facts=bool(order_results),
                evidence=[{"entity": "order", "id": str((item.get("order") or {}).get("id") or ""),
                           "number": (item.get("order") or {}).get("number"),
                           "operation_id": item.get("operation_id")} for item in order_results],
            ), ctx)
        return await self._runs.finish(run_id, ExecutionOutcome(
            status="completed", summary=candidate_answer,
            committed_facts=bool(state.get("order_results") or state.get("result")),
            evidence=[{"entity": "order", "id": str((item.get("order") or {}).get("id") or ""),
                       "number": (item.get("order") or {}).get("number"),
                       "operation_id": item.get("operation_id")} for item in order_results],
        ), ctx)

    async def _revise_order_answer(self, request: str, answer: str,
                                   verified_orders: list[dict[str, Any]], review: ReviewResult,
                                   budget: RunBudget, ctx: RequestContext) -> str:
        """Use a no-tool model call to revise only the user-facing order explanation."""
        assert self._model is not None
        prompt = {
            "request": request,
            "previous_answer": answer,
            "verified_orders": {"orders": verified_orders},
            "issues": [item.reason or item.check_id for item in review.checks if not item.passed],
        }
        messages = [
            ModelMessage(role="system", content=(
                "只修订已提交订单的说明文字。只能使用verified_orders中的事实；不可调用工具、"
                "改动订单或审批、改变数值或范围。只输出修订后的正文。"
            )),
            ModelMessage(role="user", content=json.dumps(prompt, ensure_ascii=False, default=str)),
        ]
        await budget.charge_model()
        parts: list[str] = []
        async def emit_model_event(kind: str, payload: dict[str, Any]) -> None:
            if ctx.run_id:
                await self._runs.append_event(ctx.run_id, kind, payload, ctx)
        async def consume() -> None:
            async for delta in observed_model_stream(
                self._model, messages, [], ctx, emit_model_event, purpose="order_answer_revision"
            ):
                if delta.kind == "token" and delta.content:
                    parts.append(delta.content)
                elif delta.kind == "tool_call":
                    raise AppError(ErrorCodes.VALIDATION_ERROR,
                                   "order review revision cannot invoke tools", http_status=422)

        task = asyncio.create_task(consume())
        try:
            timeout = budget.bounded_timeout(60)
            if timeout <= 0:
                await budget.check_active()
            async with asyncio.timeout(timeout):
                while not task.done():
                    await asyncio.wait({task}, timeout=min(0.1, budget.remaining_seconds))
                    await budget.check_cancelled()
                    await budget.check_active()
                await task
        except TimeoutError as exc:
            raise RunDeadlineExceeded("order review revision exceeded run deadline") from exc
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        revised = "".join(parts).strip()
        return revised[:4000] if revised else answer

    async def _settle_protected(self, state: dict, run_id: str, ctx: RequestContext):
        """结算任何异常都收敛为持久终态，并保留已提交订单事实。"""
        try:
            return await self._settle(state, run_id, ctx)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # cancellation after the mutation must not strand the run
            committed_orders = list(state.get("order_results") or [])
            if not committed_orders:
                try:
                    operations = await self._mongo.db["operations"].find({
                        "owner_id": ctx.owner_id, "run_id": run_id,
                        "action": "order_create", "status": "succeeded",
                    }).to_list(length=100)
                    for operation in operations:
                        order = await self._mongo.db["orders"].find_one({
                            "_id": operation.get("order_id"), "owner_id": ctx.owner_id,
                            "operation_id": operation["_id"],
                        })
                        committed_orders.append({"order": order or {}, "operation_id": operation["_id"]})
                except Exception as lookup_error:  # recovery will retry read-only reconciliation
                    logger.error("could not reconcile post-commit order facts run=%s error=%s",
                                 run_id, type(lookup_error).__name__)
            numbers = [str((item.get("order") or {}).get("number")) for item in committed_orders
                       if (item.get("order") or {}).get("number")]
            fact_text = "订单已提交" + ("：" + "、".join(numbers) if numbers else "，持久结果待查询") if committed_orders else "未确认订单已提交"
            message = f"{fact_text}；评审未完成（{type(exc).__name__}），不会自动重放订单提交。"
            code = "POST_COMMIT_REVIEW_FAILED" if committed_orders else "ORDER_SETTLEMENT_FAILED"
            if isinstance(exc, RunCancelled):
                code = "POST_COMMIT_REVIEW_CANCELLED" if committed_orders else "RUN_CANCELLED"
            elif isinstance(exc, (RunDeadlineExceeded, RunLimitExceeded)):
                code = "POST_COMMIT_REVIEW_LIMIT" if committed_orders else "LIMIT_EXCEEDED"
            try:
                result = ReviewResult(
                    passed=False,
                    checks=[ReviewCheck(check_id="POST_COMMIT_SETTLEMENT", passed=False,
                                        reason=message)],
                    needs_revision=False,
                    revision_count=min(2, int(state.get("revision_count", 0))),
                    incomplete_items=["POST_COMMIT_SETTLEMENT"],
                )
                await self._runs.append_event(run_id, "review", {
                    "passed": False, "checks": ["POST_COMMIT_SETTLEMENT"],
                    "details": [item.model_dump(mode="json") for item in result.checks],
                    "result": result.model_dump(mode="json"),
                    "revision_count": result.revision_count,
                    "incomplete_items": result.incomplete_items,
                }, ctx)
                await self._runs.append_event(run_id, "phase", {
                    "phase": "result", "task_type": "order", "iteration": result.revision_count,
                    "revision_count": result.revision_count,
                }, ctx)
            except Exception as event_error:
                logger.error("could not append settlement failure events run=%s error=%s",
                             run_id, type(event_error).__name__)
            return await self._runs.finish(run_id, ExecutionOutcome(
                status="failed", summary=message, error_code=code,
                committed_facts=bool(committed_orders),
                evidence=[{"entity": "order", "id": str((item.get("order") or {}).get("id") or
                                                          (item.get("order") or {}).get("_id") or ""),
                           "number": (item.get("order") or {}).get("number"),
                           "operation_id": item.get("operation_id")} for item in committed_orders],
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
        from backend.app.agent.skill_loader import select_skills
        skills = select_skills("order", "order")
        await self._runs.record_skill_manifest(run.id, [
            {"id": skill.id, "version": skill.version, "content_hash": skill.content_hash} for skill in skills
        ], run_ctx)
        await self._runs.record_specialist(run.id, "order", run_ctx)
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
                await self._live_draft_request(request.message, run_ctx, budget,
                                               skill_context=render_skill_context(skills))
                if self._model_mode == "live"
                else request.draft
            )
            if draft_request is None:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "draft is required", http_status=422)
            if self._preferences is not None:
                explicit_fields = request.draft.model_fields_set if request.draft is not None else set()
                effective = await self._preferences.effective(ctx.owner_id, {
                    "default_warehouse": draft_request.warehouse_id if "warehouse_id" in explicit_fields else None,
                    "preferred_supplier": draft_request.supplier_id if "supplier_id" in explicit_fields else None,
                    "max_lead_days": draft_request.max_lead_days if "max_lead_days" in explicit_fields else None,
                })
                draft_request = draft_request.model_copy(update={
                    "warehouse_id": draft_request.warehouse_id or effective.get("default_warehouse"),
                    "supplier_id": draft_request.supplier_id or effective.get("preferred_supplier"),
                    "max_lead_days": draft_request.max_lead_days if draft_request.max_lead_days is not None else effective.get("max_lead_days"),
                })
            await self._runs.persist_order_intent(run.id, draft_request.model_dump(mode="json"), run_ctx)
            state = await self._graph(run.graph_version).ainvoke({
                "owner_id": ctx.owner_id, "run_id": run.id, "thread_id": run.thread_id,
                "user_request": request.message,
                "request": draft_request.model_dump(mode="json"),
            }, config=workflow_config(run.thread_id, run.id, run.graph_version))
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
        return await self._settle_protected(state, run.id, run_ctx)

    async def start_existing(self, run_id: str, message: str, ctx: RequestContext, budget: RunBudget,
                             *, evidence_refs: list[dict[str, Any]] | None = None,
                             parent_call_id: str | None = None, skill_context: str = "",
                             preference_overrides: dict[str, Any] | None = None,
                             request_constraints: dict[str, Any] | None = None):
        """Continue an existing v2 chat run into the order specialist's approval graph."""
        run = await self._runs.get(run_id, ctx)
        if run.graph_version != "v2" or run.status != "running":
            raise AppError(ErrorCodes.RUN_NOT_ACTIVE, "v2 order delegation requires its active parent run", http_status=409)
        if self._model_mode != "live":
            raise AppError(ErrorCodes.DEPENDENCY_UNAVAILABLE,
                           "order specialist natural-language extraction requires the configured live model", http_status=503)
        run_ctx = RequestContext(owner_id=ctx.owner_id, request_id=ctx.request_id, run_id=run_id, actor="order")
        skills = select_skills("order", "order")
        await self._runs.record_skill_manifest(run_id, [
            {"id": skill.id, "version": skill.version, "content_hash": skill.content_hash} for skill in skills
        ], run_ctx)
        await self._runs.record_specialist(run_id, "order", run_ctx, parent_call_id)
        await self._runs.append_event(run_id, "phase", {
            "phase": "executing", "task_type": "order", "iteration": 0, "revision_count": 0,
        }, run_ctx)
        draft_request = await self._live_draft_request(message, run_ctx, budget, evidence_refs, skill_context,
                                                      request_constraints=request_constraints)
        effective = preference_overrides or {}
        clear_supplier = bool((request_constraints or {}).get("clear_preferred_supplier"))
        clear_lead = bool((request_constraints or {}).get("clear_max_lead_days"))
        draft_request = draft_request.model_copy(update={
            "warehouse_id": draft_request.warehouse_id or effective.get("default_warehouse"),
            "supplier_id": (None if clear_supplier else
                            (request_constraints or {}).get("supplier_id") or draft_request.supplier_id or effective.get("preferred_supplier")),
            "max_lead_days": (None if clear_lead else draft_request.max_lead_days
                              if draft_request.max_lead_days is not None else effective.get("max_lead_days")),
        })
        await self._runs.persist_order_intent(run_id, draft_request.model_dump(mode="json"), run_ctx)
        try:
            state = await self._graph(run.graph_version).ainvoke({
                "owner_id": ctx.owner_id, "run_id": run_id, "thread_id": run.thread_id,
                "user_request": message, "request": draft_request.model_dump(mode="json"),
            }, config=workflow_config(run.thread_id, run_id, run.graph_version))
        except Exception as exc:
            cancelled = isinstance(exc, RunCancelled) or await self._runs.cancel_requested(run_id, run_ctx)
            return await self._runs.finish(run_id, ExecutionOutcome(
                status="cancelled" if cancelled else "failed",
                summary="订单专家已取消；未提交订单。" if cancelled else "订单专家失败；未确认订单写入。",
                error_code="RUN_CANCELLED" if cancelled else "ORDER_WORKFLOW_FAILED",
            ), run_ctx)
        return await self._settle_protected(state, run_id, run_ctx)

    async def resume(self, run_id: str, request: ResumeRequest, ctx: RequestContext):
        run = await self._runs.get(run_id, ctx)
        if request.decision == "approve":
            self._ensure_order_write_provider()
        pending = run.pending_interrupt
        request_payload = request.model_dump(mode="json")
        request_hash = hashlib.sha256(json.dumps(
            request_payload, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        persisted = await self._mongo.db["runs"].find_one({"_id": run_id, "owner_id": ctx.owner_id})
        previous = (persisted or {}).get("resume_request") or {}
        prior_decision = next((item for item in (persisted or {}).get("decision_history", [])
                               if item.get("idempotency_key") == request.idempotency_key), None)
        if prior_decision:
            if prior_decision.get("request_hash") != request_hash:
                raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "decision key payload differs", http_status=409)
            if prior_decision.get("result"):
                return RunView.model_validate(prior_decision["result"])
            return await self._runs.get(run_id, ctx)
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
            state = await self._graph(run.graph_version).ainvoke(
                Command(resume=resume_value),
                config=workflow_config(run.thread_id, run_id, run.graph_version),
            )
        except Exception as exc:
            logger.exception("order workflow recovery failed error=%s", type(exc).__name__)
            cancelled = isinstance(exc, RunCancelled) or await self._runs.cancel_requested(run_id, run_ctx)
            if cancelled:
                result = await self._runs.finish(run_id, ExecutionOutcome(
                    status="cancelled", summary="订单流程已取消；未提交的订单不会创建。",
                    error_code="RUN_CANCELLED",
                ), run_ctx)
                await self._runs.record_decision_result(run_id, request.idempotency_key, result, run_ctx)
                return result
            try:
                persisted_run = await self._mongo.db["runs"].find_one({"_id": run_id, "owner_id": ctx.owner_id})
                if persisted_run and persisted_run.get("resume_request"):
                    recovered = await self._recover_one(persisted_run)
                    if recovered.status in {"completed", "failed", "cancelled", "waiting_input"}:
                        await self._runs.record_decision_result(
                            run_id, request.idempotency_key, recovered, run_ctx
                        )
                        return recovered
                    operation = await self._mongo.db["operations"].find_one({
                        "owner_id": ctx.owner_id, "action": "order_create",
                        "idempotency_key": request.idempotency_key,
                    })
                    if operation and operation.get("status") == "succeeded":
                        return recovered
            except Exception as recovery_error:
                logger.warning("immediate order recovery deferred error=%s", type(recovery_error).__name__)
            failed = await self._runs.finish(run_id, ExecutionOutcome(
                status="failed",
                summary="订单恢复失败；请查询审批与操作记录确认状态。",
                error_code="ORDER_WORKFLOW_RECOVERY_FAILED",
                committed_facts=bool(getattr(exc, "committed_order", False)),
            ), run_ctx)
            await self._runs.record_decision_result(run_id, request.idempotency_key, failed, run_ctx)
            raise AppError(ErrorCodes.DEPENDENCY_UNAVAILABLE,
                           "order workflow recovery failed", http_status=500) from exc
        result = await self._settle_protected(state, run_id, run_ctx)
        await self._runs.record_decision_result(run_id, request.idempotency_key, result, run_ctx)
        return result

    async def _recover_one(self, document: dict):
        run_id = document["_id"]
        ctx = RequestContext(owner_id=document["owner_id"], request_id="workflow-recovery", run_id=run_id)
        graph_version = document.get("graph_version", "v1")
        config = workflow_config(document["thread_id"], run_id, graph_version)
        # Preserve the no-argument v1 builder contract used by pre-P07 recovery
        # integrations; newer runs select their graph explicitly.
        graph = self._graph() if graph_version == "v1" else self._graph(graph_version)
        request = document["resume_request"]
        decision = request.get("decision")
        if decision == "approve":
            self._ensure_order_write_provider()
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
        result = await self._settle_protected(state, run_id, ctx)
        decision_key = request.get("idempotency_key")
        if decision_key:
            await self._runs.record_decision_result(run_id, decision_key, result, ctx)
        return result

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
