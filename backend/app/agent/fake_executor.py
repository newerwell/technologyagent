"""P02 FakeAgent：固定示例 token 与只读假工具，不访问模型/业务写入。"""

from __future__ import annotations

import asyncio

from backend.app.agent.budget import RunBudget
from backend.app.contracts.agent import ExecutionOutcome, ExecutorInput
from backend.app.ports.executor import EventSink

FAKE_TOOL_NAME = "fake_readonly_catalog"
FAKE_TOOL_CALL_ID = "call_fake_readonly_1"


class FakeAgent:
    """确定性假执行器；输出用于验证协议/UI，不代表真实模型或查询。"""

    def __init__(
        self,
        *,
        token_delay: float = 0.2,
        tool_failure: bool = False,
    ) -> None:
        self._token_delay = token_delay
        self._tool_failure = tool_failure

    @staticmethod
    def _chunks(message: str) -> list[str]:
        text = (
            "这是 FakeAgent 的示例流式输出，用于验证 P02 协议。"
            "已收到你的消息：「" + message[:80] + "」。"
            "未调用真实模型，也未访问或修改任何业务数据。"
        )
        size = 7
        return [text[index : index + size] for index in range(0, len(text), size)]

    async def execute(
        self, request: ExecutorInput, sink: EventSink, budget: RunBudget
    ) -> ExecutionOutcome:
        message_id = "msg_" + request.run_id + "_assistant"
        pieces = self._chunks(request.message)
        for index, piece in enumerate(pieces):
            await budget.check_cancelled()
            await budget.check_active()
            await sink.emit(
                "token",
                {"message_id": message_id, "delta": piece, "actor": "main"},
            )
            if index == 1:
                await sink.emit(
                    "tool_started",
                    {
                        "call_id": FAKE_TOOL_CALL_ID,
                        "name": FAKE_TOOL_NAME,
                        "actor": "main",
                        "args_summary": {"query": "示例只读", "simulation": True},
                        "simulation": True,
                    },
                )
                if self._tool_failure:
                    await sink.emit(
                        "tool_finished",
                        {
                            "call_id": FAKE_TOOL_CALL_ID,
                            "status": "error",
                            "result_summary": "",
                            "source": "fake",
                            "error": "FAKE_TOOL_FAILURE",
                            "simulation": True,
                        },
                    )
                    raise RuntimeError("fake readonly tool failed")
                await sink.emit(
                    "tool_finished",
                    {
                        "call_id": FAKE_TOOL_CALL_ID,
                        "status": "success",
                        "result_summary": "FakeAgent 示例结果（未访问真实业务）",
                        "source": "fake",
                        "simulation": True,
                    },
                )
            await asyncio.sleep(self._token_delay)

        await budget.check_cancelled()
        return ExecutionOutcome(status="completed", summary="".join(pieces))
