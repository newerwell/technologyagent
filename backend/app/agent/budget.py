"""P02 有界执行：取消检查与活跃 deadline；P03 再增加模型/工具计数。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class RunCancelled(RuntimeError):
    """执行器应停止后续步骤；由 ChatService 转成 cancelled 终态。"""


class RunDeadlineExceeded(RuntimeError):
    """run 活跃执行时间超限。"""


class RunLimitExceeded(RuntimeError):
    """模型或工具调用次数超过共享预算。"""


class RunBudget:
    def __init__(
        self,
        run_id: str,
        *,
        max_active_seconds: float = 180.0,
        monotonic: Callable[[], float] = time.monotonic,
        model_counter: Callable[[], Awaitable[bool]] | None = None,
        tool_counter: Callable[[], Awaitable[bool]] | None = None,
        max_model_calls: int = 20,
        max_tool_calls: int = 30,
    ) -> None:
        self.run_id = run_id
        self.max_active_seconds = max_active_seconds
        self.max_model_calls = max_model_calls
        self.max_tool_calls = max_tool_calls
        self._monotonic = monotonic
        self._started = monotonic()
        self._cancelled = asyncio.Event()
        self._model_counter = model_counter
        self._tool_counter = tool_counter
        self.model_calls = 0
        self.tool_calls = 0

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    async def check_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise RunCancelled("run cancelled")

    async def check_active(self) -> None:
        if self.remaining_seconds <= 0:
            raise RunDeadlineExceeded("run active deadline exceeded")

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.max_active_seconds - (self._monotonic() - self._started))

    def bounded_timeout(self, operation_timeout: float) -> float:
        """Bound a single operation by both its own limit and the run deadline."""
        return min(operation_timeout, self.remaining_seconds)

    async def charge_model(self) -> None:
        await self.check_cancelled()
        await self.check_active()
        if self._model_counter is not None:
            allowed = await self._model_counter()
        else:
            allowed = self.model_calls < self.max_model_calls
        if not allowed:
            raise RunLimitExceeded("model call limit exceeded")
        self.model_calls += 1

    async def charge_tool(self) -> None:
        await self.check_cancelled()
        await self.check_active()
        if self._tool_counter is not None:
            allowed = await self._tool_counter()
        else:
            allowed = self.tool_calls < self.max_tool_calls
        if not allowed:
            raise RunLimitExceeded("tool call limit exceeded")
        self.tool_calls += 1
