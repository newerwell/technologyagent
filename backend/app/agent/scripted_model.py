"""脚本模型：离线测试/固定 demo，用确定性 ModelDelta 驱动同一 GraphExecutor。"""

from __future__ import annotations

import json
from itertools import count
from collections.abc import AsyncIterator, Sequence
from typing import Callable

from backend.app.contracts.agent import ModelDelta, ModelMessage, ModelToolCall
from backend.app.contracts.common import RequestContext
from backend.app.ports.tools import ToolSpec

_CALL_IDS = count(1)


class ScriptedModel:
    def __init__(
        self,
        steps: Sequence[Sequence[ModelDelta]] | None = None,
        *,
        responder: Callable[[Sequence[ModelMessage]], Sequence[ModelDelta]] | None = None,
    ) -> None:
        self._steps = [list(step) for step in (steps or [])]
        self._responder = responder
        self.calls = 0

    async def stream(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec],
        ctx: RequestContext,
    ) -> AsyncIterator[ModelDelta]:
        self.calls += 1
        if self._responder is not None:
            deltas = list(self._responder(messages))
        elif self._steps:
            deltas = self._steps.pop(0)
        else:
            deltas = [ModelDelta(kind="token", content="已完成。")]
        for delta in deltas:
            yield delta


def token(text: str) -> ModelDelta:
    return ModelDelta(kind="token", content=text)


def call_tool(name: str, arguments: dict, call_id: str | None = None) -> ModelDelta:
    return ModelDelta(
        kind="tool_call",
        tool_call=ModelToolCall(id=call_id or f"call_{next(_CALL_IDS)}", name=name, arguments=json.dumps(arguments, ensure_ascii=False)),
    )


class DemoScriptedModel(ScriptedModel):
    """Fake 模式：先读一条本地只读数据，再输出明确标注的示例回答。"""

    def __init__(self) -> None:
        super().__init__()

    async def stream(self, messages, tools, ctx):
        if not any(message.role == "tool" for message in messages):
            yield call_tool("inventory_page", {"warehouse_id": "W01", "page": 1, "page_size": 1}, "call_demo_1")
            return
        last = next((message for message in reversed(messages) if message.role == "tool"), None)
        suffix = ""
        if last is not None:
            try:
                parsed = json.loads(last.content)
                records = ((parsed.get("data") or {}).get("records") or [])
                if records:
                    item = records[0]
                    suffix = f" 已读取 {item.get('part_id')} / {item.get('warehouse_id')} 一条本地只读库存记录。"
            except (TypeError, ValueError):
                suffix = ""
        yield token("这是 ScriptedModel 的离线示例输出，用于验证 P03 受控工具循环。" + suffix)
        import asyncio
        await asyncio.sleep(0.25)
        yield token("未调用真实模型；工具数据来自 local_seed。")
