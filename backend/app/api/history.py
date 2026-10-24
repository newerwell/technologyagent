"""P02 会话历史接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.app.api.dependencies import envelope, get_container, get_context
from backend.app.bootstrap import Container
from backend.app.contracts.common import Envelope, RequestContext
from backend.app.contracts.events import ConversationView, DeleteResult, ThreadView

router = APIRouter(prefix="/api/conversations", tags=["history"])


@router.get("", response_model=Envelope[list[ThreadView]])
async def list_conversations(
    request: Request,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[list[ThreadView]]:
    data = await container.runs.list_conversations(ctx)
    return envelope(data, request, container, scope=ctx.owner_id)


@router.get("/{thread_id}", response_model=Envelope[ConversationView])
async def get_conversation(
    thread_id: str,
    request: Request,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[ConversationView]:
    data = await container.runs.get_conversation(thread_id, ctx)
    return envelope(data, request, container, scope=ctx.owner_id)


@router.delete("/{thread_id}", response_model=Envelope[DeleteResult])
async def delete_conversation(
    thread_id: str,
    request: Request,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[DeleteResult]:
    data = await container.runs.delete_conversation(thread_id, ctx)
    return envelope(data, request, container, scope=ctx.owner_id)
