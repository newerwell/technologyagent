"""Owner-scoped preparation and human decisions for generic business proposals."""

from fastapi import APIRouter, Depends, Request

from backend.app.api.dependencies import envelope, get_container, get_context
from backend.app.bootstrap import Container
from backend.app.contracts.common import AppError, ErrorCodes, RequestContext
from backend.app.contracts.mutations import (
    MutationDecisionRequest,
    MutationExecuteRequest,
    MutationProposalRequest,
)
from backend.app.repositories.indexes import APPROVALS

router = APIRouter(prefix="/api/mutations", tags=["mutations"])
_ALLOWED = {"supplier_create", "supplier_update_status", "part_create", "inventory_inbound",
            "inventory_outbound", "inventory_receive", "order_update_status", "order_update"}


@router.post("/proposals")
async def create_proposal(body: MutationProposalRequest, request: Request,
                          ctx: RequestContext = Depends(get_context),
                          container: Container = Depends(get_container)):
    if body.action not in _ALLOWED:
        raise AppError(ErrorCodes.UNSUPPORTED_OPERATION, "unsupported proposal action", 405)
    data = await container.approvals.request_mutation(body.action, body.payload, ctx)
    return envelope(data, request, container, scope=ctx.owner_id)


@router.get("/proposals")
async def list_proposals(request: Request, ctx: RequestContext = Depends(get_context),
                         container: Container = Depends(get_container)):
    cursor = container.mongo.db[APPROVALS].find({"owner_id": ctx.owner_id, "proposal_payload": {"$exists": True},
                                                 "status": {"$in": ["pending", "rejected", "consumed"]}}).sort("created_at", -1).limit(100)
    data = []
    async for doc in cursor:
        data.append({"approval_id": doc["_id"], "proposal_id": doc["proposal_id"],
                     "action": doc["action"], "payload": doc["proposal_payload"],
                     "run_id": doc.get("run_id"), "fact_snapshot": doc.get("fact_snapshot", {}),
                     "version": doc["version"], "decision": doc.get("decision"),
                     "status": ("consumed" if doc.get("status") == "consumed" else
                                "approved" if doc.get("decision") == "approve" else doc["status"]),
                     "created_at": doc["created_at"]})
    return envelope(data, request, container, scope=ctx.owner_id)


@router.post("/proposals/{approval_id}/resolve")
async def resolve_proposal(approval_id: str, body: MutationDecisionRequest, request: Request,
                           ctx: RequestContext = Depends(get_context),
                           container: Container = Depends(get_container)):
    data = await container.approvals.resolve_mutation(approval_id, body.decision, body.decision_key,
                                                      ctx, expected_version=body.expected_version)
    return envelope(data, request, container, scope=ctx.owner_id)


@router.post("/proposals/{approval_id}/execute")
async def execute_proposal(approval_id: str, body: MutationExecuteRequest, request: Request,
                           ctx: RequestContext = Depends(get_context),
                           container: Container = Depends(get_container)):
    approval = await container.mongo.db[APPROVALS].find_one({"_id": approval_id, "owner_id": ctx.owner_id,
                                                             "proposal_payload": {"$exists": True}})
    if approval is None:
        raise AppError(ErrorCodes.NOT_FOUND, "business proposal not found", 404)
    action = approval.get("action")
    modules = ({"orders", "inventory", "parts", "suppliers"} if action in {"order_update", "order_update_status"}
               else {"inventory", "parts"} if action in {"inventory_inbound", "inventory_outbound", "inventory_receive"}
               else {"suppliers"} if action.startswith("supplier_")
               else {"parts"} if action.startswith("part_") else set())
    for module in modules:
        from backend.app.integrations.business_provider import ensure_local_capability
        ensure_local_capability(container.business_providers, module, write=True)
    if action == "inventory_receive":
        data = await container.inventory_mutations.receive(
            **approval["proposal_payload"], approval_id=approval_id,
            idempotency_key=body.idempotency_key, ctx=ctx,
        )
    else:
        data = await container.business_mutations.execute(approval_id, body.idempotency_key, ctx,
                                                          expected_action=action)
    return envelope(data, request, container, scope=ctx.owner_id)
