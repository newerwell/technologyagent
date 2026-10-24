"""P02 执行器与事件 sink 接口；不把 SSE 连接生命周期放进执行器。"""

from __future__ import annotations

from typing import Any, Protocol

from backend.app.agent.budget import RunBudget
from backend.app.contracts.agent import ExecutorInput, ExecutionOutcome
from backend.app.contracts.events import EventEnvelope, EventType


class EventSink(Protocol):
    async def emit(self, kind: EventType, payload: dict[str, Any]) -> EventEnvelope: ...


class AgentExecutor(Protocol):
    async def execute(
        self, request: ExecutorInput, sink: EventSink, budget: RunBudget
    ) -> ExecutionOutcome: ...
