"""P02 run 查询、事件重放与取消。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from backend.app.api.dependencies import envelope, get_container, get_context
from backend.app.bootstrap import Container
from backend.app.contracts.common import Envelope, RequestContext
from backend.app.contracts.events import EventEnvelope, RunView
from backend.app.contracts.order_workflow import ResumeRequest

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("/{run_id}", response_model=Envelope[RunView])
async def get_run(
    run_id: str,
    request: Request,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[RunView]:
    data = await container.runs.get(run_id, ctx)
    return envelope(data, request, container, scope=ctx.owner_id)


@router.get("/{run_id}/events", response_model=Envelope[list[EventEnvelope]])
async def run_events(
    run_id: str,
    request: Request,
    after_seq: int = Query(default=0, ge=0),
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[list[EventEnvelope]]:
    data = await container.runs.events(run_id, after_seq, ctx)
    return envelope(data, request, container, scope=ctx.owner_id)


@router.post("/{run_id}/cancel", response_model=Envelope[RunView])
async def cancel_run(
    run_id: str,
    request: Request,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[RunView]:
    data = await container.chat.cancel(run_id, ctx)
    return envelope(data, request, container, scope=ctx.owner_id)


@router.post("/{run_id}/resume", response_model=Envelope[RunView])
async def resume_run(
    run_id: str, body: ResumeRequest, request: Request,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[RunView]:
    data = await container.order_workflows.resume(run_id, body, ctx)
    return envelope(data, request, container, scope=ctx.owner_id)
