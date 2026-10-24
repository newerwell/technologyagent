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


async def stream_run_events(
    runs, run_id: str, ctx: RequestContext, *, poll_interval: float = 0.05
):
    """读取持久事件直到 stream_end；终态后继续排空 last_seq，避免漏末事件。"""
    after_seq = 0
    while True:
        events = await runs.events(run_id, after_seq, ctx)
        for event in events:
            after_seq = event.seq
            yield _sse(event)
            if event.type == "stream_end":
                return
        current = await runs.get(run_id, ctx)
        if current.status in {"completed", "failed", "cancelled"}:
            drain_attempts = 0
            while after_seq < current.last_seq and drain_attempts < 50:
                batch = await runs.events(run_id, after_seq, ctx)
                if not batch:
                    drain_attempts += 1
                    await asyncio.sleep(0.01)
                    continue
                drain_attempts = 0
                for event in batch:
                    after_seq = event.seq
                    yield _sse(event)
                    if event.type == "stream_end":
                        return
            return
        await asyncio.sleep(poll_interval)


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

    return StreamingResponse(
        stream_run_events(container.runs, run.id, ctx),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )