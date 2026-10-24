"""P03 模型端口：只输出归一化 token/tool_call/usage，不直接写 SSE。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from backend.app.contracts.agent import ModelDelta, ModelMessage
from backend.app.contracts.common import RequestContext


class ModelPort(Protocol):
    def stream(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[object],
        ctx: RequestContext,
    ) -> AsyncIterator[ModelDelta]: ...
