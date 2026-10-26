"""Persist a bounded, privacy-safe trace for model calls outside the main graph node."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from time import perf_counter
from uuid import uuid4

from backend.app.contracts.agent import ModelDelta, ModelMessage
from backend.app.contracts.common import RequestContext
from backend.app.ports.model import ModelPort

EventWriter = Callable[[str, dict], Awaitable[object]]


async def observed_model_stream(
    model: ModelPort,
    messages: Sequence[ModelMessage],
    tools: Sequence[object],
    ctx: RequestContext,
    emit: EventWriter,
    *,
    purpose: str,
) -> AsyncIterator[ModelDelta]:
    """Yield the original stream while persisting start/finish and usage coverage."""
    call_id = "model_" + uuid4().hex
    started = perf_counter()
    await emit("model_started", {"call_id": call_id, "actor": ctx.actor, "purpose": purpose})
    usage: dict | None = None
    error_code: str | None = None
    status = "success"
    try:
        async for delta in model.stream(messages, tools, ctx):
            if delta.kind == "usage" and isinstance(delta.usage, dict):
                usage = delta.usage
            yield delta
    except BaseException as exc:
        status = "error"
        error_code = type(exc).__name__.upper()[:80]
        raise
    finally:
        safe_usage = {
            key: value for key, value in (usage or {}).items()
            if isinstance(key, str) and key.endswith("_tokens")
            and isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        await emit("model_finished", {
            "call_id": call_id,
            "status": status,
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "usage": safe_usage or None,
            "usage_status": "reported" if safe_usage else "missing",
            "error_code": error_code,
        })
