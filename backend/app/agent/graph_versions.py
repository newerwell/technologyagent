"""新run与旧run按持久graph_version路由。"""

from __future__ import annotations

import re

from backend.app.agent.budget import RunBudget
from backend.app.contracts.agent import ExecutionOutcome, ExecutorInput
from backend.app.contracts.common import RequestContext
from backend.app.ports.executor import EventSink


_ORDER_CLAUSE = re.compile(
    r"(?:然后|再|并且|并)?\s*(?:准备[^，,；;。]{0,30}订单|创建订单|提交订单|生成订单|采购下单|下单)"
)


def route_graph_version(version: str | None) -> str:
    # Missing field is a pre-P07 persisted run and must stay on its original graph.
    resolved = version or "v1"
    if resolved not in {"v1", "v2"}:
        raise ValueError(f"unsupported persisted graph version: {resolved}")
    return resolved


async def route_executor(executor, request: ExecutorInput, sink: EventSink,
                         budget: RunBudget) -> ExecutionOutcome:
    version = route_graph_version(request.graph_version)
    if version == "v1":
        return await executor._execute_graph(request, sink, budget)

    from backend.app.agent.harness import classify_task, extract_request_constraints
    from backend.app.agent.specialists.dispatcher import SpecialistDispatcher
    from backend.app.agent.skill_loader import render_skill_context, select_skills
    from backend.app.agent.versions.v2 import build_specialist_subgraph

    if request.ctx.actor != "main":
        return ExecutionOutcome(status="failed", summary="专家不能递归委派。", error_code="DELEGATION_RECURSION")
    task_type = classify_task(request.message)
    analyst_task = task_type in {"inventory", "supplier", "analysis"} or any(
        word in request.message for word in ("分析", "报告", "图表")
    )
    intent_message = re.sub(r"(?:不要|无需|不需要|不必|暂不|禁止|拒绝|不考虑)[^，,。；;!?]{0,60}",
                            "", request.message)
    order_task = _ORDER_CLAUSE.search(intent_message) is not None
    specialist = "analyst" if analyst_task else "main"
    dispatcher = SpecialistDispatcher(max_delegations=2)
    if analyst_task and order_task:
        combined_skills = {skill.id: skill for skill in select_skills("inventory", "analyst")}
        if any(word in request.message for word in ("报告", "报表")):
            combined_skills.update({skill.id: skill for skill in select_skills("report", "analyst")})
        if task_type in {"supplier", "analysis"}:
            combined_skills.update({skill.id: skill for skill in select_skills(task_type, "analyst")})
        skill_set = tuple(combined_skills.values())
    else:
        skill_set = select_skills(task_type, specialist)
    if getattr(executor, "_runs", None) is not None and request.ctx.run_id:
        await executor._runs.record_skill_manifest(request.ctx.run_id, [
            {"id": skill.id, "version": skill.version, "content_hash": skill.content_hash} for skill in skill_set
        ], request.ctx)
        if specialist != "main":
            await executor._runs.record_specialist(request.run_id, specialist, request.ctx,
                                                   f"delegate_{request.run_id}_{specialist}")
    if specialist == "main":
        outcome = None
        if not order_task:
            return await executor._execute_graph(request, sink, budget)
    else:
        async def invoke(child_request):
            ctx = RequestContext(owner_id=request.ctx.owner_id, request_id=request.ctx.request_id,
                                 run_id=request.run_id, actor=child_request.specialist)
            child = request.model_copy(update={"ctx": ctx, "graph_version": "v2",
                "message": child_request.task, "skill_context": render_skill_context(skill_set),
                "request_constraints": extract_request_constraints(request.message)})
            # The nested subgraph is an explicit adapter boundary. The child is pinned
            # to a concrete specialist execution and cannot return to this router.
            graph = build_specialist_subgraph(lambda _payload: executor._execute_graph(child, sink, budget))
            return (await graph.ainvoke({"request": child_request}))["result"]

        analysis_task = request.message
        if order_task:
            clause = _ORDER_CLAUSE.search(request.message)
            if clause is not None:
                analysis_task = request.message[:clause.start()].strip(" ，,；;。")
        outcome = await dispatcher.dispatch(
            owner_id=request.ctx.owner_id, run_id=request.run_id, specialist=specialist,
            task=analysis_task, data_scope={"task_type": task_type}, evidence_refs=[],
            preferences={}, parent_call_id=f"delegate_{request.run_id}_{specialist}", budget=budget, invoke=invoke,
            recursive=False,
        )
    if not order_task:
        return outcome
    if outcome is not None and outcome.status != "completed":
        return outcome
    order_workflows = getattr(executor, "_order_workflows", None)
    if order_workflows is None:
        return ExecutionOutcome(status="failed", summary="订单专家未装配。", error_code="SPECIALIST_UNAVAILABLE")
    async def invoke_order(child_request):
        order_skills = select_skills("order", "order")
        run = await order_workflows.start_existing(
            request.run_id, child_request.task, request.ctx, budget,
            evidence_refs=child_request.evidence_refs, parent_call_id=child_request.parent_call_id,
            skill_context=render_skill_context(order_skills),
        )
        return ExecutionOutcome(
            status=run.status if run.status in {"completed", "failed", "cancelled", "waiting_input"} else "failed",
            summary=run.summary, error_code=run.error_code,
            committed_facts=run.committed_facts,
            pending_interrupt=run.pending_interrupt.model_dump(mode="json") if run.pending_interrupt else None,
        )

    try:
        return await dispatcher.dispatch(
            owner_id=request.ctx.owner_id, run_id=request.run_id, specialist="order",
            task=request.message, data_scope={"task_type": "order"},
            evidence_refs=outcome.evidence if outcome is not None else [], preferences={},
            parent_call_id=f"delegate_{request.run_id}_order", budget=budget, invoke=invoke_order,
        )
    except Exception as exc:
        return ExecutionOutcome(status="failed", summary=f"订单专家执行失败：{type(exc).__name__}。",
                                error_code=getattr(exc, "code", "ORDER_SPECIALIST_FAILED"))
    if run.status == "waiting_input":
        return ExecutionOutcome(status="waiting_input", summary=run.summary,
                                pending_interrupt=run.pending_interrupt.model_dump(mode="json") if run.pending_interrupt else None)
    return ExecutionOutcome(status=run.status if run.status in {"completed", "failed", "cancelled"} else "failed",
                            summary=run.summary, error_code=run.error_code,
                            committed_facts=run.committed_facts)
