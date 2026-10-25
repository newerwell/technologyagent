"""新run与旧run按持久graph_version路由。"""

from __future__ import annotations

from backend.app.agent.budget import RunBudget, RunCancelled, RunDeadlineExceeded, RunLimitExceeded
from backend.app.contracts.agent import ExecutionOutcome, ExecutorInput
from backend.app.contracts.common import RequestContext
from backend.app.ports.executor import EventSink


def route_graph_version(version: str | None) -> str:
    resolved = version or "v1"
    if resolved not in {"v1", "v2"}:
        raise ValueError(f"unsupported persisted graph version: {resolved}")
    return resolved


async def _preference_command(executor, request: ExecutorInput, action: str, values: dict) -> ExecutionOutcome:
    preferences = getattr(executor, "_preferences", None)
    if preferences is None:
        return ExecutionOutcome(status="failed", summary="偏好服务不可用。", error_code="SPECIALIST_UNAVAILABLE")
    owner_id = request.ctx.owner_id
    if action == "remember":
        from backend.app.contracts.preferences import RememberPreferenceRequest
        for key, value in values.items():
            await preferences.remember(owner_id, RememberPreferenceRequest(key=key, value=value, remember=True))
        return ExecutionOutcome(status="completed", summary="已按你的明确要求保存偏好。")
    if action == "delete_all":
        for key in preferences.KEYS:
            await preferences.delete(owner_id, key)
        return ExecutionOutcome(status="completed", summary="已删除当前用户保存的偏好。")
    stored = await preferences.list(owner_id)
    if not stored:
        return ExecutionOutcome(status="completed", summary="当前没有已保存的偏好。")
    display = "；".join(f"{key}={value}" for key, value in sorted(stored.items()))
    return ExecutionOutcome(status="completed", summary=f"当前已保存的偏好：{display}。")


async def route_executor(executor, request: ExecutorInput, sink: EventSink,
                         budget: RunBudget) -> ExecutionOutcome:
    version = route_graph_version(request.graph_version)
    if version == "v1":
        return await executor._execute_graph(request, sink, budget)

    from backend.app.agent.harness import classify_task, extract_request_constraints
    from backend.app.agent.request_intent import parse_request_intent
    from backend.app.agent.specialists.dispatcher import SpecialistDispatcher
    from backend.app.agent.skill_loader import render_skill_context, select_skills_for_request
    from backend.app.agent.versions.v2 import build_specialist_subgraph

    if request.ctx.actor != "main":
        return ExecutionOutcome(status="failed", summary="专家不能递归委派。", error_code="DELEGATION_RECURSION")
    intent = parse_request_intent(request.message)
    if intent.preference_action:
        return await _preference_command(executor, request, intent.preference_action, intent.preference_values)

    task_type = classify_task(request.message)
    constraints = {**extract_request_constraints(request.message), **intent.constraints}
    explicit_preference_keys = set()
    if constraints.get("warehouse_ids"):
        explicit_preference_keys.add("default_warehouse")
    if constraints.get("supplier_id"):
        explicit_preference_keys.add("preferred_supplier")
    if constraints.get("max_lead_days") is not None:
        explicit_preference_keys.add("max_lead_days")
    preferences_service = getattr(executor, "_preferences", None)
    stored_preferences = await preferences_service.list(request.ctx.owner_id) if preferences_service else {}
    effective_preferences = dict(stored_preferences)
    # Explicit current-turn fields override saved defaults. Explicit clear is
    # represented separately so None cannot accidentally restore a default.
    if constraints.get("warehouse_ids"):
        effective_preferences["default_warehouse"] = constraints["warehouse_ids"][0]
    elif stored_preferences.get("default_warehouse"):
        constraints["warehouse_ids"] = [stored_preferences["default_warehouse"]]
    if constraints.get("supplier_id"):
        effective_preferences["preferred_supplier"] = constraints["supplier_id"]
    elif constraints.get("clear_preferred_supplier"):
        effective_preferences.pop("preferred_supplier", None)
    if constraints.get("max_lead_days") is not None:
        effective_preferences["max_lead_days"] = constraints["max_lead_days"]
    elif constraints.get("clear_max_lead_days"):
        effective_preferences.pop("max_lead_days", None)
    elif ("max_lead_days" in stored_preferences
          and (task_type == "supplier" or intent.order_prepare or intent.order_query)):
        constraints["max_lead_days"] = stored_preferences["max_lead_days"]
    elif not (task_type == "supplier" or intent.order_prepare or intent.order_query):
        effective_preferences.pop("max_lead_days", None)
    if not (task_type == "supplier" or intent.order_prepare or intent.order_query):
        effective_preferences.pop("preferred_supplier", None)
    elif task_type == "supplier" and "preferred_supplier" in effective_preferences and not constraints.get("supplier_id"):
        constraints["preferred_supplier_id"] = effective_preferences["preferred_supplier"]
    constraints["preference_sources"] = {
        key: ("explicit_request" if key in explicit_preference_keys
              else "preference")
        for key in ("default_warehouse", "preferred_supplier", "max_lead_days") if key in effective_preferences
    }
    effective_constraints = request.request_constraints or constraints
    request = request.model_copy(update={"request_constraints": effective_constraints})

    order_query = intent.order_query
    order_prepare = intent.order_prepare
    if intent.order_negated:
        order_prepare = False
    analysis_task = bool(intent.analysis_tasks) or (
        task_type in {"inventory", "supplier", "analysis"} and not order_prepare and not order_query
    )
    if analysis_task:
        feature_task = request.message
        specialist = "analyst"
        skill_set = select_skills_for_request(feature_task, "analyst")
    elif order_query or order_prepare:
        specialist = "order"
        skill_set = select_skills_for_request(request.message, "order")
    else:
        specialist = "main"
        skill_set = ()

    if getattr(executor, "_runs", None) is not None and request.ctx.run_id:
        await executor._runs.record_skill_manifest(request.run_id, [
            {"id": skill.id, "version": skill.version, "content_hash": skill.content_hash} for skill in skill_set
        ], request.ctx)
        if specialist != "main":
            await executor._runs.record_specialist(request.run_id, specialist, request.ctx,
                                                   f"delegate_{request.run_id}_{specialist}")

    if specialist == "main":
        return await executor._execute_graph(request, sink, budget)

    dispatcher = SpecialistDispatcher(max_delegations=2)

    async def invoke_graph(child_request):
        ctx = RequestContext(owner_id=request.ctx.owner_id, request_id=request.ctx.request_id,
                             run_id=request.run_id, actor=child_request.specialist)
        child = request.model_copy(update={
            "ctx": ctx, "graph_version": "v2", "message": child_request.task,
            "skill_context": render_skill_context(skill_set),
            "request_constraints": effective_constraints,
        })
        graph = build_specialist_subgraph(lambda _payload: executor._execute_graph(child, sink, budget))
        return (await graph.ainvoke({"request": child_request}))["result"]

    analysis_outcome = None
    if analysis_task:
        # Only the non-empty analysis portion is delegated. An order-only
        # request must never create an invalid empty analyst request.
        analysis_message = "；".join(intent.analysis_tasks) or request.message
        analysis_outcome = await dispatcher.dispatch(
            owner_id=request.ctx.owner_id, run_id=request.run_id, specialist="analyst",
            task=analysis_message, data_scope={"task_type": task_type}, evidence_refs=[],
            preferences=effective_preferences, parent_call_id=f"delegate_{request.run_id}_analyst",
            budget=budget, invoke=invoke_graph,
        )
        if not order_prepare or analysis_outcome.status != "completed":
            return analysis_outcome

    if order_query:
        return await dispatcher.dispatch(
            owner_id=request.ctx.owner_id, run_id=request.run_id, specialist="order",
            task=request.message, data_scope={"task_type": "order_query", "read_only": True},
            evidence_refs=[], preferences=effective_preferences,
            parent_call_id=f"delegate_{request.run_id}_order_query", budget=budget,
            invoke=invoke_graph,
        )

    if not order_prepare:
        return analysis_outcome or await executor._execute_graph(request, sink, budget)
    workflows = getattr(executor, "_order_workflows", None)
    if workflows is None:
        return ExecutionOutcome(status="failed", summary="订单专家未装配。", error_code="SPECIALIST_UNAVAILABLE")

    async def invoke_order(child_request):
        order_skills = select_skills_for_request(request.message, "order")
        run = await workflows.start_existing(
            request.run_id, child_request.task, request.ctx, budget,
            evidence_refs=child_request.evidence_refs, parent_call_id=child_request.parent_call_id,
            skill_context=render_skill_context(order_skills), preference_overrides=effective_preferences,
            request_constraints=effective_constraints,
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
            task=request.message, data_scope={"task_type": "order_prepare"},
            evidence_refs=analysis_outcome.evidence if analysis_outcome else [],
            preferences=effective_preferences, parent_call_id=f"delegate_{request.run_id}_order",
            budget=budget, invoke=invoke_order,
        )
    except (RunCancelled, RunDeadlineExceeded, RunLimitExceeded):
        # Control-flow outcomes must reach ChatService unchanged; ordinary
        # service failures retain their diagnostic classification.
        raise
    except Exception as exc:
        return ExecutionOutcome(status="failed", summary=f"订单专家执行失败：{type(exc).__name__}。",
                                error_code=getattr(exc, "code", "ORDER_SPECIALIST_FAILED"))
