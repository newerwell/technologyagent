"""Persist a bounded, privacy-safe trace for model calls outside the main graph node."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from time import perf_counter
from uuid import uuid4

import httpx

from backend.app.agent.budget import RunBudget
from backend.app.contracts.agent import ModelDelta, ModelMessage
from backend.app.contracts.common import RequestContext
from backend.app.integrations.model import ModelProviderError
from backend.app.ports.model import ModelPort

EventWriter = Callable[[str, dict], Awaitable[object]]


@dataclass(frozen=True)
class ObservedModelResponse:
    deltas: list[ModelDelta]
    successful_call_id: str
    usage: dict | None


def _retryable_before_delta(exc: BaseException) -> bool:
    if isinstance(exc, ModelProviderError):
        return exc.code in {"MODEL_TIMEOUT", "MODEL_UNAVAILABLE"}
    return isinstance(exc, (httpx.TransportError, TimeoutError))


def _safe_usage(deltas: Sequence[ModelDelta]) -> dict | None:
    usage = next((delta.usage for delta in reversed(deltas)
                  if delta.kind == "usage" and isinstance(delta.usage, dict)), None)
    if usage is None:
        return None
    safe = {
        key: value for key, value in usage.items()
        if isinstance(key, str) and key.endswith("_tokens")
        and isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    return safe or None


async def collect_model_response(
    model: ModelPort,
    messages: Sequence[ModelMessage],
    tools: Sequence[object],
    ctx: RequestContext,
    budget: RunBudget,
    emit: EventWriter | None,
    *,
    purpose: str,
    timeout_seconds: float = 60.0,
) -> ObservedModelResponse:
    """Collect one complete response, with one bounded pre-delta transport retry.

    Each actual request is charged and traced independently. Failed attempt deltas
    are discarded and never concatenated with a later successful response.
    """
    async def noop_emit(_kind: str, _payload: dict) -> None:
        return None

    event_writer = emit or noop_emit
    logical_deadline = perf_counter() + budget.bounded_timeout(timeout_seconds)
    if logical_deadline <= perf_counter():
        await budget.check_active()
        raise ModelProviderError("model request exceeded its run deadline", code="MODEL_TIMEOUT")

    for attempt in range(2):
        await budget.check_cancelled()
        await budget.check_active()
        remaining = min(logical_deadline - perf_counter(), budget.remaining_seconds)
        if remaining <= 0:
            await budget.check_active()
            raise ModelProviderError("model request exceeded its logical deadline", code="MODEL_TIMEOUT")
        await budget.charge_model()
        call_id = "model_" + uuid4().hex
        started = perf_counter()
        await event_writer("model_started", {
            "call_id": call_id, "actor": ctx.actor, "purpose": purpose,
        })
        deltas: list[ModelDelta] = []

        async def collect() -> None:
            async for delta in model.stream(messages, tools, ctx):
                deltas.append(delta)

        task = asyncio.create_task(collect())
        try:
            while not task.done():
                remaining = min(logical_deadline - perf_counter(), budget.remaining_seconds)
                if remaining <= 0:
                    await budget.check_active()
                    raise ModelProviderError("model request exceeded its logical deadline", code="MODEL_TIMEOUT")
                await asyncio.wait({task}, timeout=min(0.1, remaining))
                await budget.check_cancelled()
                await budget.check_active()
            await task
            await budget.check_cancelled()
            await budget.check_active()
            if perf_counter() >= logical_deadline:
                raise ModelProviderError(
                    "model response completed after its logical deadline", code="MODEL_TIMEOUT"
                )
        except BaseException as exc:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            usage = _safe_usage(deltas)
            code = getattr(exc, "code", None) or type(exc).__name__.upper()[:80]
            await event_writer("model_finished", {
                "call_id": call_id,
                "status": "error",
                "duration_ms": round((perf_counter() - started) * 1000, 3),
                "usage": usage,
                "usage_status": "reported" if usage is not None else "missing",
                "error_code": code,
            })
            if attempt == 0 and not deltas and _retryable_before_delta(exc):
                await budget.check_cancelled()
                await budget.check_active()
                if logical_deadline > perf_counter():
                    continue
            raise

        usage = _safe_usage(deltas)
        await event_writer("model_finished", {
            "call_id": call_id,
            "status": "success",
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "usage": usage,
            "usage_status": "reported" if usage is not None else "missing",
        })
        return ObservedModelResponse(deltas=deltas, successful_call_id=call_id, usage=usage)

    raise AssertionError("bounded model attempt loop exhausted without a response")


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
