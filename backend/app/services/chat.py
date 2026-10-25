"""P02 对话执行协调：任务在后台写持久事件，SSE 只观察；连接关闭不取消任务。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from backend.app.agent.budget import RunBudget, RunCancelled, RunDeadlineExceeded
from backend.app.agent.fake_executor import FakeAgent
from backend.app.contracts.agent import ExecutionOutcome, ExecutorInput
from backend.app.contracts.common import Clock, ErrorCodes, RequestContext
from backend.app.contracts.events import EventEnvelope, EventType, RunView
from backend.app.ports.executor import AgentExecutor
from backend.app.services.runs import RunService

logger = logging.getLogger(__name__)


class RunEventSink:
    def __init__(self, runs: RunService, run_id: str, ctx: RequestContext) -> None:
        self._runs = runs
        self._run_id = run_id
        self._ctx = ctx

    async def emit(self, kind: EventType, payload: dict[str, Any]) -> EventEnvelope:
        return await self._runs.append_event(self._run_id, kind, payload, self._ctx)


class ChatTaskManager:
    """进程级强引用任务表；关闭观察连接不会触碰这里的 task。"""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._budgets: dict[str, RunBudget] = {}

    def register_budget(self, run_id: str, budget: RunBudget) -> None:
        """先注册通知落点，再写 run_started/启动任务；取消窗口不丢。"""
        self._budgets[run_id] = budget

    def attach_task(self, run_id: str, task: asyncio.Task[None]) -> None:
        self._tasks[run_id] = task

        def _done(completed: asyncio.Task[None]) -> None:
            self._tasks.pop(run_id, None)
            self._budgets.pop(run_id, None)
            if completed.cancelled():
                return
            error = completed.exception()
            if error is not None:
                logger.error("chat task failed: %s", error)

        task.add_done_callback(_done)

    def unregister(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)
        self._budgets.pop(run_id, None)

    def request_cancel(self, run_id: str) -> None:
        budget = self._budgets.get(run_id)
        if budget is not None:
            budget.cancel()

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._budgets.clear()

    @property
    def active_count(self) -> int:
        return len(self._tasks)


class ChatService:
    def __init__(
        self,
        runs: RunService,
        executor: AgentExecutor | None = None,
        *,
        max_active_seconds: float = 180.0,
        model_mode: str = "fake",
    ) -> None:
        self._runs = runs
        self._executor = executor or FakeAgent()
        self._tasks = ChatTaskManager()
        self._max_active_seconds = max_active_seconds
        self._model_mode = model_mode

    async def start(
        self,
        thread_id: str | None,
        message: str,
        request_id: str,
        ctx: RequestContext,
    ) -> RunView:
        run, just_created = await self._runs.create_or_get(
            thread_id, message, request_id, ctx
        )
        if not just_created:
            # 同一 request_id 的幂等重放：可观察已有事件，不重新执行或重复 run_started。
            return run
        run_ctx = RequestContext(
            owner_id=ctx.owner_id, request_id=ctx.request_id, run_id=run.id
        )
        budget = RunBudget(
            run.id,
            max_active_seconds=self._max_active_seconds,
            model_counter=lambda: self._runs.charge_model(run.id, run_ctx),
            tool_counter=lambda: self._runs.charge_tool(run.id, run_ctx),
        )
        # 预算必须先于任何 await 注册：其他请求此时取消也能落到同一个 budget。
        self._tasks.register_budget(run.id, budget)
        try:
            await self._runs.append_event(
                run.id,
                "run_started",
                {
                    "status": run.status,
                    "thread_id": run.thread_id,
                    "run_id": run.id,
                    "model_mode": self._model_mode,
                },
                run_ctx,
            )
            # 注册后、执行器启动前同步可信 DB 状态；窗口期取消不能被吞。
            current = await self._runs.get(run.id, run_ctx)
            if current.cancel_requested:
                budget.cancel()
        except Exception:
            self._tasks.unregister(run.id)
            await self._runs.finish(
                run.id,
                ExecutionOutcome(
                    status="failed",
                    summary="run_started 持久化失败，任务未启动。",
                    error_code=ErrorCodes.INTERNAL_ERROR,
                ),
                run_ctx,
            )
            raise

        task = asyncio.create_task(
            self._execute(
                run.id,
                run.thread_id,
                message,
                run.graph_version,
                run_ctx,
                budget,
            )
        )
        self._tasks.attach_task(run.id, task)
        return run

    async def _execute(
        self,
        run_id: str,
        thread_id: str,
        message: str,
        graph_version: str,
        ctx: RequestContext,
        budget: RunBudget,
    ) -> None:
        sink = RunEventSink(self._runs, run_id, ctx)
        outcome: ExecutionOutcome
        try:
            outcome = await self._executor.execute(
                ExecutorInput(
                    run_id=run_id,
                    thread_id=thread_id,
                    message=message,
                    ctx=ctx,
                    graph_version=graph_version,
                ),
                sink,
                budget,
            )
        except asyncio.CancelledError:
            raise
        except RunCancelled:
            outcome = ExecutionOutcome(status="cancelled", summary="任务已按请求取消。")
        except RunDeadlineExceeded:
            await self._safe_error(run_id, ctx, ErrorCodes.LIMIT_EXCEEDED, "run active deadline exceeded")
            outcome = ExecutionOutcome(
                status="failed",
                summary="任务超过活跃执行时限。",
                error_code=ErrorCodes.LIMIT_EXCEEDED,
            )
        except Exception as exc:  # noqa: BLE001 - 执行器错误要转成可查询终态
            await self._safe_error(
                run_id, ctx, "EXECUTION_FAILED", f"{type(exc).__name__}: {exc}"
            )
            outcome = ExecutionOutcome(
                status="failed",
                summary="执行器失败，未产生订单或业务写入。",
                error_code="EXECUTION_FAILED",
            )
        else:
            if outcome.status == "failed":
                await self._safe_error(
                    run_id, ctx, outcome.error_code or "EXECUTION_FAILED", outcome.summary or "execution failed"
                )

        if outcome.status == "waiting_input":
            # The workflow already persisted the interrupt on this run. Keep its
            # thread active for the ordinary resume endpoint.
            return
        try:
            await self._runs.finish(run_id, outcome, ctx)
        except Exception:  # noqa: BLE001
            logger.exception("failed to finish run %s", run_id)

    async def _safe_error(
        self, run_id: str, ctx: RequestContext, code: str, message: str
    ) -> None:
        try:
            await self._runs.append_event(
                run_id,
                "error",
                {"code": code, "message": message, "retryable": False},
                ctx,
            )
        except Exception:  # noqa: BLE001
            logger.debug("could not append error event for %s", run_id)

    async def cancel(self, run_id: str, ctx: RequestContext) -> RunView:
        run = await self._runs.request_cancel(run_id, ctx)
        if run.cancel_requested:
            self._tasks.request_cancel(run_id)
        return run

    async def shutdown(self) -> None:
        await self._tasks.shutdown()

    @property
    def active_count(self) -> int:
        return self._tasks.active_count

    @staticmethod
    def request_id() -> str:
        return uuid4().hex
