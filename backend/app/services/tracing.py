"""Owner-scoped read-only summaries from persisted run/event/operation facts."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from backend.app.contracts.common import AppError, ErrorCodes, RequestContext
from backend.app.contracts.tracing import RunTraceSummary, ToolCallTrace
from backend.app.services.recovery import classify_recovery
from backend.app.repositories.indexes import APPROVALS, ARTIFACTS, EVENTS, OPERATIONS, ORDERS, RUNS
from backend.app.repositories.mongo import MongoResources


def _error_code(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.split(":", 1)[0].split(None, 1)[0][:80]


def _elapsed(start: datetime | None, finish: datetime | None) -> float | None:
    if start is None or finish is None:
        return None
    return max(0.0, (finish - start).total_seconds() * 1000)


class TraceService:
    def __init__(self, mongo: MongoResources) -> None:
        self._mongo = mongo

    async def summary(self, run_id: str, ctx: RequestContext) -> RunTraceSummary:
        db = self._mongo.db
        run = await db[RUNS].find_one({"_id": run_id, "owner_id": ctx.owner_id})
        if run is None:
            raise AppError(ErrorCodes.NOT_FOUND, "run not found", 404)

        events = [row async for row in db[EVENTS].find(
            {"_id": {"$exists": True}, "run_id": run_id, "owner_id": ctx.owner_id},
            {"type": 1, "at": 1, "payload": 1, "seq": 1},
        ).sort("seq", 1)]
        starts: dict[str, dict] = {}
        finishes: dict[str, dict] = {}
        model_starts: dict[str, dict] = {}
        model_finishes: dict[str, dict] = {}
        errors: list[dict[str, str]] = []
        phases: list[str] = []
        phase_trace: list[dict] = []
        sources: Counter[str] = Counter()
        for event in events:
            payload = event.get("payload") or {}
            if event.get("type") == "tool_started":
                call_id = payload.get("call_id")
                if isinstance(call_id, str):
                    starts[call_id] = event
            elif event.get("type") == "tool_finished":
                call_id = payload.get("call_id")
                if isinstance(call_id, str):
                    finishes[call_id] = event
                source = payload.get("source")
                if isinstance(source, str) and source:
                    sources[source] += 1
            elif event.get("type") == "model_started":
                call_id = payload.get("call_id")
                if isinstance(call_id, str):
                    model_starts[call_id] = event
            elif event.get("type") == "model_finished":
                call_id = payload.get("call_id")
                if isinstance(call_id, str):
                    model_finishes[call_id] = event
            elif event.get("type") == "phase":
                phase = payload.get("phase")
                if isinstance(phase, str):
                    phases.append(phase)
                    phase_trace.append({"phase": phase, "at": event.get("at"),
                                        "iteration": payload.get("iteration", 0),
                                        "task_type": payload.get("task_type", "general")})
            elif event.get("type") == "error":
                code = _error_code(payload.get("code")) or "UNKNOWN_ERROR"
                errors.append({"code": code, "event_id": str(event.get("_id", ""))})

        calls: list[ToolCallTrace] = []
        for call_id, started in starts.items():
            start_payload = started.get("payload") or {}
            finished = finishes.get(call_id)
            finish_payload = (finished or {}).get("payload") or {}
            status = finish_payload.get("status") if finished else "running"
            if status not in {"success", "error"}:
                status = "running"
            source = finish_payload.get("source") if status == "success" else None
            calls.append(ToolCallTrace(
                call_id=call_id,
                tool_name=str(start_payload.get("name") or "unknown"),
                actor=str(start_payload.get("actor") or "main"),
                parent_call_id=start_payload.get("parent_call_id"),
                status=status,
                source=source,
                duration_ms=_elapsed(started.get("at"), (finished or {}).get("at")),
                error_code=_error_code(finish_payload.get("error")) if status == "error" else None,
            ))
        calls.sort(key=lambda item: item.call_id)

        model_usage: Counter[str] = Counter()
        model_duration = 0.0
        model_errors = 0
        for finish in model_finishes.values():
            payload = finish.get("payload") or {}
            duration = payload.get("duration_ms")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                model_duration += duration
            model_errors += payload.get("status") == "error"
            usage = payload.get("usage")
            if isinstance(usage, dict):
                for key, value in usage.items():
                    if isinstance(key, str) and isinstance(value, (int, float)) and not isinstance(value, bool):
                        model_usage[key] += value

        approval_counts: Counter[str] = Counter()
        async for approval in db[APPROVALS].find(
            {"owner_id": ctx.owner_id, "run_id": run_id}, {"status": 1, "decision": 1},
        ):
            approval_counts[str(approval.get("status", "unknown"))] += 1
        artifacts = [{
            "artifact_id": row["_id"], "kind": row.get("kind", "unknown"),
            "filename": row.get("filename", ""), "mime": row.get("mime", ""),
            "size_bytes": row.get("size_bytes", 0),
            "created_at": row.get("created_at"),
        } async for row in db[ARTIFACTS].find(
            {"owner_id": ctx.owner_id, "run_id": run_id},
            {"kind": 1, "filename": 1, "mime": 1, "size_bytes": 1, "created_at": 1},
        ).sort("created_at", 1)]
        operation_rows = [row async for row in db[OPERATIONS].find(
            {"owner_id": ctx.owner_id, "run_id": run_id}, {"status": 1, "action": 1, "result": 1},
        )]
        operation_ids = [row["_id"] for row in operation_rows]
        order_count = await db[ORDERS].count_documents(
            {"owner_id": ctx.owner_id, "operation_id": {"$in": operation_ids}}
        ) if operation_ids else 0

        registered_tools = 0
        try:
            from mcp_server.tools.specs import ALL_TOOL_SPECS
            registered_tools = len(ALL_TOOL_SPECS)
        except Exception:  # noqa: BLE001 - diagnostics must survive a missing optional registry
            registered_tools = 0
        return RunTraceSummary(
            run_id=run_id, thread_id=run["thread_id"], request_id=run.get("request_id"), status=run["status"],
            phase=run.get("phase"), created_at=run.get("created_at"), finished_at=run.get("finished_at"),
            duration_ms=_elapsed(run.get("created_at"), run.get("finished_at")),
            model={"mode": run.get("model_mode", "unknown"),
                   "calls": len(model_starts) if model_starts else run.get("model_calls_used", 0),
                   "duration_ms": round(model_duration, 3),
                   "failed": model_errors,
                   "usage": dict(model_usage) if model_usage else run.get("model_usage")},
            tools={"registered_count": registered_tools, "calls": len(calls),
                   "succeeded": sum(call.status == "success" for call in calls),
                   "failed": sum(call.status == "error" for call in calls),
                   "running": sum(call.status == "running" for call in calls)},
            tool_calls=calls, phases=phases, phase_trace=phase_trace, errors=errors,
            approvals=dict(approval_counts), artifacts=artifacts, data_sources=dict(sources),
            business_effects={"operations": len(operation_rows), "succeeded_operations": sum(
                row.get("status") == "succeeded" for row in operation_rows),
                "orders": order_count, "committed_facts": bool(run.get("committed_facts", False))},
            committed_facts=bool(run.get("committed_facts", False)),
            recovery={"action": classify_recovery(run, operation_rows).action,
                      "reason": classify_recovery(run, operation_rows).reason,
                      "retry_business_write": classify_recovery(run, operation_rows).retry_business_write},
        )
