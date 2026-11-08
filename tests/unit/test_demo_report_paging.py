import json

import pytest

from backend.app.agent.scripted_model import DemoScriptedModel
from backend.app.contracts.agent import ModelMessage
from backend.app.contracts.common import RequestContext


@pytest.mark.asyncio
async def test_demo_model_reads_a_complete_page_for_formal_report():
    model = DemoScriptedModel()
    messages = [ModelMessage(role="user", content="查询 W01 仓库库存并生成 JSON 报告")]

    deltas = [delta async for delta in model.stream(messages, [], RequestContext(
        owner_id="owner_test", request_id="request_test", run_id="run_test"))]

    call = next(delta.tool_call for delta in deltas if delta.kind == "tool_call")
    args = json.loads(call.arguments)
    assert args["warehouse_id"] == "W01"
    assert args["page"] == 1
    assert args["page_size"] >= 50
