"""P02 对话/run/event 服务：原子认领、seq、终态与 owner 隔离。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, TypeVar
from uuid import uuid4

from pymongo.errors import DuplicateKeyError, OperationFailure

from backend.app.contracts.agent import ExecutionOutcome
from backend.app.contracts.common import (
    AppError,
    Clock,
    ErrorCodes,
    RequestContext,
)
from backend.app.contracts.events import (
    PAYLOAD_MODELS,
    ConversationView,
    DeleteResult,
    EventEnvelope,
    EventType,
    MessageView,
    RunFinishedPayload,
    RunView,
    StreamEndPayload,
    ThreadView,
)
from backend.app.repositories.indexes import SCHEMA_VERSION
from backend.app.repositories.messages import MessageRepository
from backend.app.repositories.mongo import MongoResources
from backend.app.repositories.runs import RunRepository

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_STATUSES = {"created", "running"}
RECOVERY_SUMMARY = "任务因服务重启失败（PROCESS_RESTARTED）；P02 无检查点，不能假装恢复。"

T = TypeVar("T")


def _hash_request(thread_id: str | None, message: str, request_payload: dict[str, Any] | None = None) -> str:
    payload = json.dumps(
        {"thread_id": thread_id, "message": message, "request_payload": request_payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _title(message: str) -> str:
    normalized = " ".join(message.split())
    return normalized[:36] or "新对话"


class RunService:
    def __init__(self, mongo: MongoResources, clock: Clock) -> None:
        self._mongo = mongo
        self._clock = clock
        self._runs = RunRepository(mongo)
        self._messages = MessageRepository(mongo)
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, run_id: str) -> asyncio.Lock:
        return self._locks.setdefault(run_id, asyncio.Lock())

    async def _retry_tx(
        self, operation: Callable[[Any], Awaitable[T]], attempts: int = 10
    ) -> T:
        """只重试可安全重放的 TransientTransactionError/WriteConflict。

        事件 id、最终 message id 在调用前固定，因此重试不会产生第二份逻辑记录。
        """
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                async with self._mongo.transaction() as session:
                    return await operation(session)
            except OperationFailure as exc:
                last_error = exc
                transient = exc.has_error_label("TransientTransactionError")
                if transient or exc.code in {112, 251}:
                    await asyncio.sleep(0.01 * (attempt + 1))
                    continue
                raise
        raise last_error or RuntimeError("transaction retry exhausted")

    def _thread_view(self, doc: dict[str, Any]) -> ThreadView:
        return ThreadView(
            id=doc["_id"],
            title=doc.get("title", ""),
            active_run_id=doc.get("active_run_id"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

    def _message_view(self, doc: dict[str, Any], model_mode: str | None = None) -> MessageView:
        return MessageView(
            id=doc["_id"],
            thread_id=doc["thread_id"],
            run_id=doc["run_id"],
            role=doc["role"],
            content=doc["content"],
            created_at=doc["created_at"],
            model_mode=model_mode,
            evidence=doc.get("evidence", []),
        )

    def _run_view(self, doc: dict[str, Any]) -> RunView:
        status = doc["status"]
        cancel_requested = bool(doc.get("cancel_requested", False))
        actions: list[str] = []
        if status in ACTIVE_STATUSES and not cancel_requested:
            actions.append("cancel")
        if status == "waiting_input":
            actions.append("resume")
        return RunView(
            id=doc["_id"],
            thread_id=doc["thread_id"],
            status=status,
            phase=doc.get("phase"),
            last_seq=doc.get("last_seq", 0),
            cancel_requested=cancel_requested,
            available_actions=actions,
            error_code=doc.get("error_code"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
            finished_at=doc.get("finished_at"),
            pending_interrupt=doc.get("pending_interrupt"),
        )

    async def create(
        self,
        thread_id: str | None,
        message: str,
        request_id: str,
        ctx: RequestContext,
    ) -> RunView:
        run, _ = await self.create_or_get(thread_id, message, request_id, ctx)
        return run

    async def create_or_get(
        self,
        thread_id: str | None,
        message: str,
        request_id: str,
        ctx: RequestContext,
        *,
        request_payload: dict[str, Any] | None = None,
    ) -> tuple[RunView, bool]:
        """返回 (run, just_created)；相同 request_id 重放返回 False，不重复启动任务。"""
        request_hash = _hash_request(thread_id, message, request_payload)
        existing = await self._runs.find_by_request(ctx.owner_id, request_id)
        if existing is not None:
            if existing.get("request_hash") != request_hash:
                raise AppError(
                    ErrorCodes.IDEMPOTENCY_CONFLICT,
                    "request_id was already used with a different payload",
                    http_status=409,
                )
            return self._run_view(existing), False

        now = self._clock.now()
        run_id = f"run_{uuid4().hex}"
        resolved_thread_id = thread_id or f"thr_{uuid4().hex}"
        user_message_id = f"msg_{run_id}_user"

        async def operation(session):
            # 竞争重试也必须先重新检查 request_id；相同 payload 返回原 run。
            existing_in_tx = await self._runs.find_by_request(
                ctx.owner_id, request_id, session=session
            )
            if existing_in_tx is not None:
                if existing_in_tx.get("request_hash") != request_hash:
                    raise AppError(
                        ErrorCodes.IDEMPOTENCY_CONFLICT,
                        "request_id was already used with a different payload",
                        http_status=409,
                    )
                return self._run_view(existing_in_tx), False

            if thread_id is None:
                await self._runs.insert_thread(
                    {
                        "_id": resolved_thread_id,
                        "owner_id": ctx.owner_id,
                        "title": _title(message),
                        "active_run_id": run_id,
                        "created_at": now,
                        "updated_at": now,
                        "schema_version": SCHEMA_VERSION,
                    },
                    session=session,
                )
            else:
                thread = await self._runs.get_thread(
                    ctx.owner_id, thread_id, session=session
                )
                if thread is None:
                    raise AppError(
                        ErrorCodes.NOT_FOUND, "conversation not found", http_status=404
                    )
                if thread.get("deleting"):
                    raise AppError(
                        ErrorCodes.NOT_FOUND, "conversation is being deleted", http_status=404
                    )
                active_id = thread.get("active_run_id")
                if active_id is not None:
                    active_run = await self._runs.get_run(
                        ctx.owner_id, active_id, session=session
                    )
                    if (
                        active_run is not None
                        and active_run.get("request_id") == request_id
                        and active_run.get("request_hash") == request_hash
                    ):
                        return self._run_view(active_run), False
                    raise AppError(
                        ErrorCodes.ACTIVE_RUN_EXISTS,
                        "thread already has an active run",
                        http_status=409,
                    )
                claimed = await self._runs.claim_thread(
                    ctx.owner_id, thread_id, run_id, now, session=session
                )
                if not claimed:
                    current = await self._runs.get_thread(
                        ctx.owner_id, thread_id, session=session
                    )
                    if current is None or current.get("deleting"):
                        raise AppError(
                            ErrorCodes.NOT_FOUND,
                            "conversation is being deleted",
                            http_status=404,
                        )
                    active_current = current.get("active_run_id")
                    if active_current is not None:
                        active_run = await self._runs.get_run(
                            ctx.owner_id, active_current, session=session
                        )
                        if (
                            active_run is not None
                            and active_run.get("request_id") == request_id
                            and active_run.get("request_hash") == request_hash
                        ):
                            return self._run_view(active_run), False
                    raise AppError(
                        ErrorCodes.ACTIVE_RUN_EXISTS,
                        "thread already has an active run",
                        http_status=409,
                    )

            await self._runs.insert_run(
                {
                    "_id": run_id,
                    "thread_id": resolved_thread_id,
                    "owner_id": ctx.owner_id,
                    "status": "running",
                    "phase": None,
                    "last_seq": 0,
                    "request_id": request_id,
                    "request_hash": request_hash,
                    "message": message,
                    "request_payload": request_payload,
                    "cancel_requested": False,
                    "graph_version": "v1",
                    "model_calls": 0,
                    "tool_calls": 0,
                    "error_code": None,
                    "created_at": now,
                    "updated_at": now,
                    "schema_version": SCHEMA_VERSION,
                },
                session=session,
            )
            await self._messages.insert_user(
                message_id=user_message_id,
                thread_id=resolved_thread_id,
                run_id=run_id,
                owner_id=ctx.owner_id,
                content=message,
                created_at=now,
                session=session,
            )

        try:
            result = await self._retry_tx(operation)
            if result is not None:
                return result
        except DuplicateKeyError:
            existing = await self._runs.find_by_request(ctx.owner_id, request_id)
            if existing is not None and existing.get("request_hash") == request_hash:
                return self._run_view(existing), False
            raise AppError(
                ErrorCodes.IDEMPOTENCY_CONFLICT,
                "request_id is already in use",
                http_status=409,
            ) from None
        except AppError as exc:
            if exc.code != ErrorCodes.ACTIVE_RUN_EXISTS:
                raise
            # 竞争者的第一事务可能尚未提交；短暂重查 request_id，避免把幂等重放误报为 409。
            for delay in (0.005, 0.01, 0.02, 0.04, 0.08):
                await asyncio.sleep(delay)
                existing = await self._runs.find_by_request(ctx.owner_id, request_id)
                if existing is not None:
                    if existing.get("request_hash") != request_hash:
                        raise AppError(
                            ErrorCodes.IDEMPOTENCY_CONFLICT,
                            "request_id was already used with a different payload",
                            http_status=409,
                        )
                    return self._run_view(existing), False
            raise

        document = await self._runs.get_run(ctx.owner_id, run_id)
        if document is None:
            raise AppError(
                ErrorCodes.DEPENDENCY_UNAVAILABLE,
                "run was created but cannot be read back",
                http_status=503,
                retryable=True,
            )
        return self._run_view(document), True

    async def get(self, run_id: str, ctx: RequestContext) -> RunView:
        document = await self._runs.get_run(ctx.owner_id, run_id)
        if document is None:
            raise AppError(ErrorCodes.NOT_FOUND, "run not found", http_status=404)
        return self._run_view(document)

    async def append_event(
        self,
        run_id: str,
        kind: EventType,
        payload: dict[str, Any],
        ctx: RequestContext,
    ) -> EventEnvelope:
        if kind in {"run_finished", "stream_end"}:
            raise AppError(
                ErrorCodes.RUN_NOT_ACTIVE,
                "terminal events are written by finish()",
                http_status=409,
            )
        model = PAYLOAD_MODELS[kind]
        try:
            model.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                ErrorCodes.VALIDATION_ERROR, f"invalid {kind} payload: {exc}", http_status=422
            ) from exc

        event_id = f"evt_{uuid4().hex}"
        at = self._clock.now()

        async def operation(session):
            run = await self._runs.bump_seq(ctx.owner_id, run_id, session=session)
            if run is None:
                existing = await self._runs.get_run(
                    ctx.owner_id, run_id, session=session
                )
                if existing is None:
                    raise AppError(ErrorCodes.NOT_FOUND, "run not found", http_status=404)
                raise AppError(
                    ErrorCodes.RUN_NOT_ACTIVE, "run is not active", http_status=409
                )
            event = EventEnvelope(
                type=kind,
                event_id=event_id,
                seq=run["last_seq"],
                thread_id=run["thread_id"],
                run_id=run_id,
                at=at,
                payload=payload,
            )
            await self._runs.insert_event(
                {
                    "_id": event_id,
                    "schema_version": 1,
                    "type": kind,
                    "seq": event.seq,
                    "thread_id": event.thread_id,
                    "run_id": event.run_id,
                    "owner_id": ctx.owner_id,
                    "at": event.at,
                    "payload": event.payload,
                },
                session=session,
            )
            return event

        async with self._lock_for(run_id):
            return await self._retry_tx(operation)

    async def events(
        self, run_id: str, after_seq: int, ctx: RequestContext
    ) -> list[EventEnvelope]:
        run = await self._runs.get_run(ctx.owner_id, run_id)
        if run is None:
            raise AppError(ErrorCodes.NOT_FOUND, "run not found", http_status=404)
        docs = await self._runs.list_events(ctx.owner_id, run_id, after_seq)
        return [
            EventEnvelope(
                schema_version=doc.get("schema_version", 1),
                type=doc["type"],
                event_id=doc["_id"],
                seq=doc["seq"],
                thread_id=doc["thread_id"],
                run_id=doc["run_id"],
                at=doc["at"],
                payload=doc["payload"],
            )
            for doc in docs
        ]

    async def finish(
        self, run_id: str, outcome: ExecutionOutcome, ctx: RequestContext
    ) -> RunView:
        now = self._clock.now()
        final_message_id = f"msg_{run_id}_assistant"
        finished_event_id = f"evt_{uuid4().hex}"
        end_event_id = f"evt_{uuid4().hex}"

        async def operation(session):
            run = await self._runs.get_run(ctx.owner_id, run_id, session=session)
            if run is None:
                raise AppError(ErrorCodes.NOT_FOUND, "run not found", http_status=404)
            if run["status"] in TERMINAL_STATUSES:
                return self._run_view(run)

            status = outcome.status
            summary = outcome.summary
            if run.get("cancel_requested") and status == "completed" and not outcome.committed_facts:
                status = "cancelled"
                summary = "任务已按请求取消。"

            await self._messages.upsert_final(
                message_id=final_message_id,
                thread_id=run["thread_id"],
                run_id=run_id,
                owner_id=ctx.owner_id,
                content=summary,
                evidence=outcome.evidence,
                created_at=now,
                session=session,
            )
            seq_finished = run["last_seq"] + 1
            seq_end = seq_finished + 1
            finished_event = EventEnvelope(
                type="run_finished",
                event_id=finished_event_id,
                seq=seq_finished,
                thread_id=run["thread_id"],
                run_id=run_id,
                at=now,
                payload=RunFinishedPayload(
                    status=status, summary=summary
                ).model_dump(),
            )
            end_event = EventEnvelope(
                type="stream_end",
                event_id=end_event_id,
                seq=seq_end,
                thread_id=run["thread_id"],
                run_id=run_id,
                at=now,
                payload=StreamEndPayload(
                    reason=status, last_seq=seq_end
                ).model_dump(),
            )
            for event in (finished_event, end_event):
                await self._runs.insert_event(
                    {
                        "_id": event.event_id,
                        "schema_version": 1,
                        "type": event.type,
                        "seq": event.seq,
                        "thread_id": event.thread_id,
                        "run_id": event.run_id,
                        "owner_id": ctx.owner_id,
                        "at": event.at,
                        "payload": event.payload,
                    },
                    session=session,
                )
            updated = await self._runs.update_terminal(
                ctx.owner_id,
                run_id,
                status=status,
                last_seq=seq_end,
                now=now,
                error_code=outcome.error_code,
                session=session,
            )
            if updated is None:
                current = await self._runs.get_run(
                    ctx.owner_id, run_id, session=session
                )
                if current is not None and current["status"] in TERMINAL_STATUSES:
                    return self._run_view(current)
                raise AppError(
                    ErrorCodes.RUN_NOT_ACTIVE, "run terminal update failed", http_status=409
                )
            await self._runs.release_thread(
                ctx.owner_id, run["thread_id"], run_id, now, session=session
            )
            return self._run_view(updated)

        async with self._lock_for(run_id):
            return await self._retry_tx(operation)

    async def charge_model(
        self, run_id: str, ctx: RequestContext, *, limit: int = 20
    ) -> bool:
        return await self._runs.increment_usage(
            ctx.owner_id, run_id, "model_calls", limit=limit
        )

    async def wait_for_input(
        self, run_id: str, interrupt: dict[str, Any], ctx: RequestContext
    ) -> RunView:
        """写入可恢复中断与 waiting_input stream_end；不写终态消息或释放 thread。"""
        now = self._clock.now()
        interrupt_id = f"evt_{uuid4().hex}"
        end_id = f"evt_{uuid4().hex}"

        async def operation(session):
            run = await self._runs.get_run(ctx.owner_id, run_id, session=session)
            if run is None:
                raise AppError(ErrorCodes.NOT_FOUND, "run not found", http_status=404)
            if run.get("status") == "waiting_input" and run.get("pending_interrupt") == interrupt:
                return self._run_view(run)
            if run.get("status") != "running":
                raise AppError(ErrorCodes.RUN_NOT_ACTIVE, "run is not active", http_status=409)
            events = [
                EventEnvelope(type="interrupt", event_id=interrupt_id, seq=run["last_seq"] + 1,
                              thread_id=run["thread_id"], run_id=run_id, at=now, payload=interrupt),
                EventEnvelope(type="stream_end", event_id=end_id, seq=run["last_seq"] + 2,
                              thread_id=run["thread_id"], run_id=run_id, at=now,
                              payload=StreamEndPayload(reason="waiting_input", last_seq=run["last_seq"] + 2).model_dump()),
            ]
            for event in events:
                await self._runs.insert_event({
                    "_id": event.event_id, "schema_version": 1, "type": event.type,
                    "seq": event.seq, "thread_id": event.thread_id, "run_id": run_id,
                    "owner_id": ctx.owner_id, "at": event.at, "payload": event.payload,
                }, session=session)
            updated = await self._runs.update_waiting(
                ctx.owner_id, run_id, interrupt=interrupt, last_seq=events[-1].seq,
                now=now, session=session,
            )
            if updated is None:
                raise AppError(ErrorCodes.RUN_NOT_ACTIVE, "run wait transition failed", http_status=409)
            return self._run_view(updated)

        async with self._lock_for(run_id):
            return await self._retry_tx(operation)

    async def resume_waiting(
        self, run_id: str, interrupt_id: str, expected_version: int | None,
        ctx: RequestContext, resume_request: dict[str, Any],
    ) -> tuple[RunView, bool]:
        now = self._clock.now()
        async with self._lock_for(run_id):
            async with self._mongo.transaction() as session:
                run = await self._runs.get_run(ctx.owner_id, run_id, session=session)
                if run is None:
                    raise AppError(ErrorCodes.NOT_FOUND, "run not found", http_status=404)
                previous = run.get("resume_request")
                if previous and previous.get("idempotency_key") == resume_request.get("idempotency_key"):
                    if previous.get("request_hash") != resume_request.get("request_hash"):
                        raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "decision key payload differs", http_status=409)
                    return self._run_view(run), False
                pending = run.get("pending_interrupt") or {}
                if (pending.get("interrupt_id") != interrupt_id
                        or (expected_version is not None and pending.get("version") != expected_version)):
                    raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "interrupt id or version is stale", http_status=409)
                updated = await self._runs.claim_resume(
                    ctx.owner_id, run_id, interrupt_id, expected_version, resume_request,
                    now, session=session,
                )
                if updated is None:
                    current = await self._runs.get_run(ctx.owner_id, run_id, session=session)
                    previous = (current or {}).get("resume_request") or {}
                    if previous.get("idempotency_key") == resume_request.get("idempotency_key"):
                        if previous.get("request_hash") != resume_request.get("request_hash"):
                            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT, "decision key payload differs", http_status=409)
                        return self._run_view(current), False
                    raise AppError(ErrorCodes.RUN_NOT_ACTIVE, "run is not waiting for input", http_status=409)
                return self._run_view(updated), True

    async def charge_tool(
        self, run_id: str, ctx: RequestContext, *, limit: int = 30
    ) -> bool:
        return await self._runs.increment_usage(
            ctx.owner_id, run_id, "tool_calls", limit=limit
        )

    async def cancel_requested(self, run_id: str, ctx: RequestContext) -> bool:
        run = await self._runs.get_run(ctx.owner_id, run_id)
        if run is None:
            raise AppError(ErrorCodes.NOT_FOUND, "run not found", http_status=404)
        return bool(run.get("cancel_requested"))

    async def persist_order_intent(self, run_id: str, intent: dict[str, Any], ctx: RequestContext) -> None:
        result = await self._mongo.db["runs"].update_one(
            {"_id": run_id, "owner_id": ctx.owner_id, "status": "running", "cancel_requested": False},
            {"$set": {"order_intent": intent, "updated_at": self._clock.now()}},
        )
        if result.modified_count != 1:
            raise AppError(ErrorCodes.RUN_NOT_ACTIVE, "order run was cancelled before intent was saved", http_status=409)

    async def request_cancel(self, run_id: str, ctx: RequestContext) -> RunView:
        now = self._clock.now()
        initial = await self._runs.get_run(ctx.owner_id, run_id)
        if initial is None:
            raise AppError(ErrorCodes.NOT_FOUND, "run not found", http_status=404)
        if initial.get("status") == "waiting_input":
            return await self.finish(run_id, ExecutionOutcome(
                status="cancelled", summary="审批等待已取消；未创建订单。"
            ), ctx)
        async with self._lock_for(run_id):
            document = await self._runs.set_cancel_requested(ctx.owner_id, run_id, now)
            if document is None:
                existing = await self._runs.get_run(ctx.owner_id, run_id)
                if existing is None:
                    raise AppError(ErrorCodes.NOT_FOUND, "run not found", http_status=404)
                return self._run_view(existing)
            return self._run_view(document)

    async def list_conversations(self, ctx: RequestContext) -> list[ThreadView]:
        return [self._thread_view(doc) for doc in await self._runs.list_threads(ctx.owner_id)]

    async def get_conversation(self, thread_id: str, ctx: RequestContext) -> ConversationView:
        thread = await self._runs.get_thread(ctx.owner_id, thread_id)
        if thread is None:
            raise AppError(ErrorCodes.NOT_FOUND, "conversation not found", http_status=404)
        message_docs = await self._messages.list_thread(ctx.owner_id, thread_id)
        modes: dict[str, str | None] = {}
        for run_id in {doc["run_id"] for doc in message_docs}:
            events = await self._runs.list_events(ctx.owner_id, run_id, 0)
            started = next((item for item in events if item.get("type") == "run_started"), None)
            mode = (started or {}).get("payload", {}).get("model_mode")
            modes[run_id] = mode if mode in {"fake", "live"} else None
        messages = [self._message_view(doc, modes.get(doc["run_id"])) for doc in message_docs]
        latest = await self._runs.latest_run_for_thread(ctx.owner_id, thread_id)
        return ConversationView(
            thread=self._thread_view(thread),
            messages=messages,
            latest_run=self._run_view(latest) if latest else None,
        )

    async def delete_conversation(
        self, thread_id: str, ctx: RequestContext
    ) -> DeleteResult:
        now = self._clock.now()

        async def operation(session):
            thread = await self._runs.get_thread(
                ctx.owner_id, thread_id, session=session
            )
            if thread is None:
                raise AppError(
                    ErrorCodes.NOT_FOUND, "conversation not found", http_status=404
                )
            if thread.get("active_run_id") is not None:
                raise AppError(
                    ErrorCodes.ACTIVE_RUN_EXISTS,
                    "cannot delete a conversation with an active run",
                    http_status=409,
                )
            claimed = await self._runs.claim_for_delete(
                ctx.owner_id, thread_id, now, session=session
            )
            if not claimed:
                current = await self._runs.get_thread(
                    ctx.owner_id, thread_id, session=session
                )
                if current is None:
                    raise AppError(
                        ErrorCodes.NOT_FOUND,
                        "conversation not found",
                        http_status=404,
                    )
                raise AppError(
                    ErrorCodes.ACTIVE_RUN_EXISTS,
                    "conversation is already being deleted or has an active run",
                    http_status=409,
                )
            await self._messages.delete_thread(
                ctx.owner_id, thread_id, session=session
            )
            await self._runs.delete_by_thread(ctx.owner_id, thread_id, session=session)
            await self._runs.delete_thread(ctx.owner_id, thread_id, session=session)

        await self._retry_tx(operation)
        return DeleteResult(deleted=True)

    async def recover_orphans(self) -> int:
        runs = await self._runs.list_nonterminal()
        recovered = 0
        for run in runs:
            if run.get("status") == "waiting_input" and run.get("pending_interrupt"):
                # P04 中断和 graph checkpoint 已持久化，保留原 thread/run 供 resume。
                continue
            ctx = RequestContext(
                owner_id=run["owner_id"],
                request_id="startup-recovery",
                run_id=run["_id"],
            )
            try:
                await self.append_event(
                    run["_id"],
                    "error",
                    {
                        "code": "PROCESS_RESTARTED",
                        "message": "服务重启时该 run 仍未结束；P02 无检查点。",
                        "retryable": False,
                    },
                    ctx,
                )
            except Exception:  # noqa: BLE001 - 恢复必须继续尝试终态
                pass
            try:
                await self.finish(
                    run["_id"],
                    ExecutionOutcome(
                        status="failed",
                        summary=RECOVERY_SUMMARY,
                        error_code="PROCESS_RESTARTED",
                    ),
                    ctx,
                )
                recovered += 1
            except Exception:  # noqa: BLE001
                continue
        return recovered
