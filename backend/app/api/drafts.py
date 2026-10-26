"""P04 草稿与订单查询 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from backend.app.api.dependencies import envelope, get_container, get_context
from backend.app.bootstrap import Container
from backend.app.contracts.common import Envelope, Page, PageQuery, RequestContext
from backend.app.contracts.domain import PurchaseOrder
from backend.app.contracts.order_workflow import DraftPatch, DraftPrepareRequest
from backend.app.contracts.order_workflow import OrderCreateRequest, ResumeRequest
from backend.app.contracts.order_workflow import WorkflowStartRequest
from backend.app.contracts.events import RunView
from backend.app.integrations.business_provider import ensure_local_capability

router = APIRouter(prefix="/api", tags=["orders"])


@router.post("/order-workflows", response_model=Envelope[RunView])
async def start_order_workflow(
    body: WorkflowStartRequest, request: Request,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[RunView]:
    for module in ("orders", "inventory", "parts", "suppliers"):
        ensure_local_capability(container.business_providers, module)
    data = await container.order_workflows.start(body, ctx)
    return envelope(data, request, container, scope=ctx.owner_id)


@router.post("/drafts")
async def prepare_draft(
    body: DraftPrepareRequest, request: Request,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
):
    sources = {ensure_local_capability(container.business_providers, module)
               for module in ("orders", "inventory", "parts", "suppliers")}
    if len(sources) != 1:
        from backend.app.contracts.common import AppError, ErrorCodes
        raise AppError(ErrorCodes.UNSUPPORTED_OPERATION,
                       "draft preparation requires order facts from one provider", http_status=409)
    data = await container.drafts.prepare(body, ctx)
    return envelope(data, request, container, scope=ctx.owner_id, data_source=sources.pop())


@router.get("/drafts")
async def list_drafts(
    request: Request, ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
):
    return envelope(await container.drafts.list(ctx), request, container, scope=ctx.owner_id)


@router.get("/drafts/{draft_id}")
async def get_draft(
    draft_id: str, request: Request, ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
):
    return envelope(await container.drafts.get(draft_id, ctx), request, container, scope=ctx.owner_id)


@router.patch("/drafts/{draft_id}")
async def patch_draft(
    draft_id: str, body: DraftPatch, request: Request,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
):
    return envelope(await container.drafts.patch(draft_id, body, ctx), request, container, scope=ctx.owner_id)


@router.get("/orders", response_model=Envelope[Page[PurchaseOrder]])
async def list_orders(
    request: Request, page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[Page[PurchaseOrder]]:
    source = ensure_local_capability(container.business_providers, "orders")
    result = await container.orders.page(ctx.owner_id, PageQuery(page=page, page_size=page_size))
    return envelope(result, request, container, scope=ctx.owner_id, data_source=source)


@router.get("/orders/{order_id}", response_model=Envelope[PurchaseOrder])
async def get_order(
    order_id: str, request: Request,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[PurchaseOrder]:
    source = ensure_local_capability(container.business_providers, "orders")
    result = await container.orders.get(ctx.owner_id, order_id)
    if result is None:
        from backend.app.contracts.common import AppError, ErrorCodes
        raise AppError(ErrorCodes.NOT_FOUND, "order not found", http_status=404)
    return envelope(result, request, container, scope=ctx.owner_id, data_source=source)


@router.post("/drafts/{draft_id}/approval")
async def request_approval(
    draft_id: str, body: dict, request: Request,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
):
    run_id = body.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        from backend.app.contracts.common import AppError, ErrorCodes
        raise AppError(ErrorCodes.VALIDATION_ERROR, "run_id is required", http_status=422)
    data = await container.approvals.request(draft_id, run_id, ctx)
    return envelope(data, request, container, scope=ctx.owner_id)


@router.post("/approvals/{approval_id}/resolve")
async def resolve_approval(
    approval_id: str, body: ResumeRequest, request: Request,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
):
    data = await container.approvals.resolve(approval_id, body, ctx)
    return envelope(data, request, container, scope=ctx.owner_id)


@router.post("/orders/create")
async def create_order(
    body: OrderCreateRequest, request: Request,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
):
    for module in ("orders", "inventory", "parts", "suppliers"):
        ensure_local_capability(container.business_providers, module, write=True)
    data = await container.mutations.execute(
        body.draft_id, body.approval_id, body.idempotency_key, ctx
    )
    return envelope(data, request, container, scope=ctx.owner_id)


@router.post("/operations/{operation_id}/reconcile")
async def reconcile_operation(
    operation_id: str, request: Request,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
):
    data = await container.reconciliation.reconcile(operation_id, ctx)
    return envelope(data, request, container, scope=ctx.owner_id)
