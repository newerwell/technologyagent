"""P03 只读工具契约：模型/工具参数中没有 owner/run 等可信身份字段。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.app.agent.budget import RunBudget
from backend.app.contracts.common import RequestContext


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    effect: str = "read"
    capability: str = "business.read"


@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    data: Any = None
    error: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""


class ToolRegistry(Protocol):
    def available(self, ctx: RequestContext) -> list[ToolSpec]: ...

    async def invoke(
        self, name: str, arguments: dict[str, Any], ctx: RequestContext, budget: RunBudget
    ) -> ToolResult: ...
