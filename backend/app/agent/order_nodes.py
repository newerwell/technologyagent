"""P04 可恢复订单工作流；节点名是持久检查点协议的一部分。"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from backend.app.contracts.common import AppError, ErrorCodes, RequestContext
from backend.app.contracts.order_workflow import DraftItemPatch, DraftPatch, DraftPrepareRequest, ResumeRequest
from backend.app.agent.budget import RunCancelled
from backend.app.services.approvals import ApprovalService
from backend.app.services.drafts import DraftService
from backend.app.services.mutations import MutationService


class OrderWorkflowState(TypedDict, total=False):
    owner_id: str
    run_id: str
    thread_id: str
    request: dict[str, Any]
    drafts: list[dict[str, Any]]
    missing_fields: list[str]
    approval_id: str
    decision: str
    idempotency_key: str
    result: dict[str, Any]
    summary: str
    draft_cursor: int
    order_results: list[dict[str, Any]]
    rejected_drafts: list[str]


def build_order_graph(drafts: DraftService, approvals: ApprovalService,
                      mutations: MutationService, checkpointer, runs=None):
    async def check_cancelled(state: OrderWorkflowState) -> None:
        if runs is None:
            return
        ctx = RequestContext(owner_id=state["owner_id"], request_id=state["run_id"], run_id=state["run_id"])
        if await runs.cancel_requested(state["run_id"], ctx):
            raise RunCancelled("order workflow cancelled")

    async def prepare_order_v1(state: OrderWorkflowState) -> dict[str, Any]:
        await check_cancelled(state)
        ctx = RequestContext(owner_id=state["owner_id"], request_id=state["run_id"], run_id=state["run_id"])
        prepared = await drafts.prepare(DraftPrepareRequest(**state["request"]), ctx)
        return {"drafts": prepared["drafts"], "missing_fields": prepared["missing_fields"]}

    async def supplement_order_v1(state: OrderWorkflowState) -> dict[str, Any]:
        await check_cancelled(state)
        missing = list(state.get("missing_fields") or [])
        if not missing:
            return {}
        run_id = state["run_id"]
        ctx = RequestContext(owner_id=state["owner_id"], request_id=run_id, run_id=run_id)
        request = DraftPrepareRequest(**state["request"])
        for attempt in range(3):
            payload = {
                "interrupt_id": f"int_{run_id}_supplement_{attempt + 1}", "kind": "supplement",
                "draft_id": None, "version": None, "fields": missing,
                "summary": "请补充订单草稿缺少的字段。",
            }
            supplied = interrupt(payload)
            if not isinstance(supplied, dict):
                raise AppError(ErrorCodes.VALIDATION_ERROR, "supplement payload must be an object", http_status=422)
            request = request.model_copy(update=supplied)
            state["request"] = request.model_dump(mode="json")
            prepared = await drafts.prepare(request, ctx)
            missing = list(prepared["missing_fields"])
            if not missing:
                return {"request": request.model_dump(mode="json"), "drafts": prepared["drafts"], "missing_fields": []}
        raise AppError(ErrorCodes.VALIDATION_ERROR, "supplement fields remain incomplete", http_status=422)

    async def approve_order_v1(state: OrderWorkflowState) -> dict[str, Any]:
        await check_cancelled(state)
        draft_list = state.get("drafts") or []
        if not draft_list:
            return {"summary": "没有可确认的有效订单草稿。"}
        cursor = state.get("draft_cursor", 0)
        if cursor >= len(draft_list):
            return {"summary": _summary(state)}
        draft = draft_list[cursor]
        run_id = state["run_id"]
        ctx = RequestContext(owner_id=state["owner_id"], request_id=run_id, run_id=run_id)
        approval = await approvals.request(draft["id"], run_id, ctx)
        approval_id = approval["approval_id"]
        interrupt_id = f"int_{run_id}_approval_{draft['id']}_{draft['version']}"
        choice = interrupt({
            "interrupt_id": interrupt_id, "kind": "approval",
            "draft_id": draft["id"], "version": draft["version"], "fields": [],
            "summary": "请确认订单草稿后再创建订单。",
        })
        if not isinstance(choice, dict) or choice.get("decision") not in {"approve", "reject", "edit"}:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "approval decision is invalid", http_status=422)
        if choice["decision"] == "edit":
            payload = choice.get("payload") or {}
            items = payload.get("items")
            if not isinstance(items, list):
                raise AppError(ErrorCodes.VALIDATION_ERROR, "edited items are required", http_status=422)
            edited = await drafts.patch(draft["id"], DraftPatch(
                expected_version=draft["version"],
                items=[DraftItemPatch(**item) for item in items],
            ), ctx)
            updated_drafts = list(draft_list)
            updated_drafts[cursor] = edited
            return {"drafts": updated_drafts, "decision": "edit"}
        request = ResumeRequest(
            interrupt_id=interrupt_id, decision=choice["decision"],
            expected_version=draft["version"],
            idempotency_key=choice.get("idempotency_key") or f"approval_{run_id}_{draft['version']}",
        )
        await approvals.resolve(approval_id, request, ctx)
        if choice["decision"] == "reject":
            updated = {"approval_id": approval_id, "decision": "reject", "draft_cursor": cursor + 1,
                       "rejected_drafts": [*(state.get("rejected_drafts") or []), draft["id"]]}
            if cursor + 1 >= len(draft_list):
                updated["summary"] = _summary({**state, **updated})
            return updated
        return {"approval_id": approval_id, "decision": choice["decision"],
                "idempotency_key": choice.get("idempotency_key") or f"order_{run_id}_{draft['id']}_{draft['version']}",
                "drafts": draft_list, "draft_cursor": cursor}

    async def submit_order_v1(state: OrderWorkflowState) -> dict[str, Any]:
        await check_cancelled(state)
        if state.get("decision") != "approve":
            return {"summary": "草稿已拒绝；未创建订单。"}
        cursor = state.get("draft_cursor", 0)
        draft = (state.get("drafts") or [])[cursor]
        ctx = RequestContext(owner_id=state["owner_id"], request_id=state["run_id"], run_id=state["run_id"])
        result = await mutations.execute(
            draft["id"], state["approval_id"], state["idempotency_key"], ctx
        )
        results = [*(state.get("order_results") or []), result]
        updated_cursor = cursor + 1
        updated = {"result": result, "order_results": results, "draft_cursor": updated_cursor}
        if updated_cursor >= len(state.get("drafts") or []):
            updated["summary"] = _summary({**state, **updated})
        return updated

    def route_after_submit(state: OrderWorkflowState) -> str:
        return "approve" if state.get("draft_cursor", 0) < len(state.get("drafts") or []) else "end"

    def route_after_supplement(state: OrderWorkflowState) -> str:
        return "approve" if state.get("drafts") else "end"

    def route_after_approval(state: OrderWorkflowState) -> str:
        if state.get("decision") == "edit":
            return "approve"
        if state.get("decision") == "approve":
            return "submit"
        return "approve" if state.get("draft_cursor", 0) < len(state.get("drafts") or []) else "end"

    graph = StateGraph(OrderWorkflowState)
    graph.add_node("prepare_order_v1", prepare_order_v1)
    graph.add_node("supplement_order_v1", supplement_order_v1)
    graph.add_node("approve_order_v1", approve_order_v1)
    graph.add_node("submit_order_v1", submit_order_v1)
    graph.add_edge(START, "prepare_order_v1")
    graph.add_edge("prepare_order_v1", "supplement_order_v1")
    graph.add_conditional_edges("supplement_order_v1", route_after_supplement,
                                {"approve": "approve_order_v1", "end": END})
    graph.add_conditional_edges("approve_order_v1", route_after_approval,
                                {"approve": "approve_order_v1", "submit": "submit_order_v1", "end": END})
    graph.add_conditional_edges("submit_order_v1", route_after_submit, {"approve": "approve_order_v1", "end": END})
    return graph.compile(checkpointer=checkpointer)


def _summary(state: OrderWorkflowState) -> str:
    results = state.get("order_results") or []
    rejected = state.get("rejected_drafts") or []
    numbers = [result.get("order", {}).get("number") for result in results]
    numbers = [number for number in numbers if number]
    return f"已创建 {len(numbers)} 张订单（{', '.join(numbers)}）；拒绝 {len(rejected)} 张；其余草稿未创建。"


def workflow_config(thread_id: str, run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": run_id}}
