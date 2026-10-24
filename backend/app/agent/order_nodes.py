"""P04 可恢复订单工作流；节点名是持久检查点协议的一部分。"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from backend.app.contracts.common import AppError, ErrorCodes, RequestContext
from backend.app.contracts.order_workflow import DraftItemPatch, DraftPatch, DraftPrepareRequest, ResumeRequest
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


def build_order_graph(drafts: DraftService, approvals: ApprovalService,
                      mutations: MutationService, checkpointer):
    async def prepare_order_v1(state: OrderWorkflowState) -> dict[str, Any]:
        ctx = RequestContext(owner_id=state["owner_id"], request_id=state["run_id"], run_id=state["run_id"])
        prepared = await drafts.prepare(DraftPrepareRequest(**state["request"]), ctx)
        return {"drafts": prepared["drafts"], "missing_fields": prepared["missing_fields"]}

    async def supplement_order_v1(state: OrderWorkflowState) -> dict[str, Any]:
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
        draft_list = state.get("drafts") or []
        if not draft_list:
            return {"summary": "没有可确认的有效订单草稿。"}
        draft = draft_list[0]
        run_id = state["run_id"]
        ctx = RequestContext(owner_id=state["owner_id"], request_id=run_id, run_id=run_id)
        approval = await approvals.request(draft["id"], run_id, ctx)
        approval_id = approval["approval_id"]
        interrupt_id = f"int_{run_id}_approval_{draft['version']}"
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
            return {"drafts": [edited], "decision": "edit"}
        request = ResumeRequest(
            interrupt_id=interrupt_id, decision=choice["decision"],
            expected_version=draft["version"],
            idempotency_key=choice.get("idempotency_key") or f"approval_{run_id}_{draft['version']}",
        )
        await approvals.resolve(approval_id, request, ctx)
        if choice["decision"] == "reject":
            return {"approval_id": approval_id, "decision": "reject",
                    "summary": "草稿已拒绝；未创建订单。", "drafts": [draft]}
        return {"approval_id": approval_id, "decision": choice["decision"],
                "idempotency_key": choice.get("idempotency_key") or f"order_{run_id}_{draft['version']}",
                "drafts": [draft]}

    async def submit_order_v1(state: OrderWorkflowState) -> dict[str, Any]:
        if state.get("decision") != "approve":
            return {"summary": "草稿已拒绝；未创建订单。"}
        draft = (state.get("drafts") or [])[0]
        ctx = RequestContext(owner_id=state["owner_id"], request_id=state["run_id"], run_id=state["run_id"])
        result = await mutations.execute(
            draft["id"], state["approval_id"], state["idempotency_key"], ctx
        )
        return {"result": result, "summary": f"订单 {result['order']['number']} 已创建。"}

    def route_after_supplement(state: OrderWorkflowState) -> str:
        return "approve" if state.get("drafts") else "end"

    def route_after_approval(state: OrderWorkflowState) -> str:
        if state.get("decision") == "edit":
            return "approve"
        return "submit" if state.get("decision") == "approve" else "end"

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
    graph.add_edge("submit_order_v1", END)
    return graph.compile(checkpointer=checkpointer)


def workflow_config(thread_id: str, run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": run_id}}
