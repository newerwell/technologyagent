"""P02 SSE 流：启动后台任务后只观察已持久化事件。"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.app.api.dependencies import get_container, get_context
from backend.app.bootstrap import Container
from backend.app.contracts.common import RequestContext
from backend.app.contracts.events import ChatRequest, EventEnvelope

router = APIRouter(prefix="/api", tags=["chat"])


def _sse(event: EventEnvelope) -> str:
    payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.event_id}\nevent: {event.type}\ndata: {payload}\n\n"


@router.post("/chat/stream", response_class=StreamingResponse)
async def chat_stream(
    request: Request,
    payload: ChatRequest,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> StreamingResponse:
    run = await container.chat.start(
        payload.thread_id, payload.message, payload.request_id, ctx
    )
    request.state.scope = ctx.owner_id

    async def event_stream():
        after_seq = 0
        while True:
            events = await container.runs.events(run.id, after_seq, ctx)
            for event in events:
                after_seq = event.seq
                yield _sse(event)
                if event.type == "stream_end":
                    return
            if not events:
                current = await container.runs.get(run.id, ctx)
                if current.status in {"completed", "failed", "cancelled"}:
                    return
            await asyncio.sleep(0.05)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
