"""P02 有界执行：取消检查与活跃 deadline；P03 再增加模型/工具计数。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable


class RunCancelled(RuntimeError):
    """执行器应停止后续步骤；由 ChatService 转成 cancelled 终态。"""


class RunDeadlineExceeded(RuntimeError):
    """run 活跃执行时间超限。"""


class RunBudget:
    def __init__(
        self,
        run_id: str,
        *,
        max_active_seconds: float = 180.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.run_id = run_id
        self.max_active_seconds = max_active_seconds
        self._monotonic = monotonic
        self._started = monotonic()
        self._cancelled = asyncio.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    async def check_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise RunCancelled("run cancelled")

    async def check_active(self) -> None:
        if self._monotonic() - self._started > self.max_active_seconds:
            raise RunDeadlineExceeded("run active deadline exceeded")
