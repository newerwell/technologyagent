"""P03-T01 model adapter: token/tool delta, no usage, provider error/timeout."""

from __future__ import annotations

import json

import httpx
import pytest

from backend.app.contracts.agent import ModelMessage
from backend.app.contracts.common import RequestContext
from backend.app.integrations.model import ModelProviderError, OpenAICompatibleModel
from backend.app.ports.tools import ToolSpec


def _sse(*chunks: dict) -> bytes:
    body = b""
    for chunk in chunks:
        body += b"data: " + json.dumps(chunk, ensure_ascii=False).encode("utf-8") + b"\n\n"
    return body + b"data: [DONE]\n\n"


async def _collect(model, messages=None, tools=None):
    result = []
    async for delta in model.stream(
        messages or [ModelMessage(role="user", content="hi")],
        tools or [],
        RequestContext(owner_id="owner", request_id="req"),
    ):
        result.append(delta)
    return result


@pytest.mark.asyncio
async def test_streams_tokens_and_reassembles_tool_call_deltas():
    payload = _sse(
        {"choices": [{"delta": {"content": "库存"}}]},
        {"choices": [{"delta": {"content": "查询"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "inventory_page", "arguments": "{\"warehouse_id\":"},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": "\"W01\"}"}}
                        ]
                    }
                }
            ]
        },
        {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 4}},
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(200, content=payload, headers={"content-type": "text/event-stream"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleModel(
        base_url="http://model.local/v1",
        model="test-model",
        api_key="secret",
        http_client=client,
    )
    deltas = await _collect(
        model,
        tools=[ToolSpec("inventory_page", "test", {"type": "object"})],
    )
    assert "".join(d.content for d in deltas if d.kind == "token") == "库存查询"
    calls = [d.tool_call for d in deltas if d.kind == "tool_call" and d.tool_call]
    assert calls[0].id == "call_1"
    assert calls[0].name == "inventory_page"
    assert "".join(call.arguments for call in calls) == '{"warehouse_id":"W01"}'
    usage = [d.usage for d in deltas if d.kind == "usage"]
    assert usage == [{"prompt_tokens": 3, "completion_tokens": 4}]
    await client.aclose()


@pytest.mark.asyncio
async def test_no_usage_is_not_reported_as_zero():
    async def handler(request):
        return httpx.Response(
            200,
            content=_sse({"choices": [{"delta": {"content": "ok"}}]}),
            headers={"content-type": "text/event-stream"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleModel(
        base_url="http://model.local/v1", model="m", api_key="k", http_client=client
    )
    deltas = await _collect(model)
    assert not [d for d in deltas if d.kind == "usage"]
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_error_is_structured_without_key():
    async def handler(request):
        return httpx.Response(500, text="upstream unavailable")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleModel(
        base_url="http://model.local/v1", model="m", api_key="super-secret", http_client=client
    )
    with pytest.raises(ModelProviderError) as error:
        await _collect(model)
    assert error.value.code == "MODEL_PROVIDER_ERROR"
    assert "super-secret" not in str(error.value)
    await client.aclose()


@pytest.mark.asyncio
async def test_request_timeout_is_model_timeout():
    async def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleModel(
        base_url="http://model.local/v1", model="m", api_key="k", http_client=client
    )
    with pytest.raises(ModelProviderError) as error:
        await _collect(model)
    assert error.value.code == "MODEL_TIMEOUT"
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("delta", [
    {"content": "partial"},
    {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "inventory_get", "arguments": '{"inventory_id":'}}]},
])
async def test_unterminated_stream_is_protocol_error_and_never_complete(delta):
    async def handler(request):
        chunk = {"choices": [{"delta": delta}]}
        return httpx.Response(
            200,
            content=b"data: " + json.dumps(chunk).encode() + b"\n\n",
            headers={"content-type": "text/event-stream"},
        )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleModel(
        base_url="http://model.local/v1", model="m", api_key="k", http_client=client
    )
    with pytest.raises(ModelProviderError) as error:
        await _collect(model)
    assert error.value.code == "MODEL_PROTOCOL_ERROR"
    await client.aclose()


@pytest.mark.asyncio
async def test_finish_reason_is_a_valid_terminal_without_usage_or_done():
    async def handler(request):
        body = b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleModel(base_url="http://model.local/v1", model="m", api_key="k", http_client=client)
    deltas = await _collect(model)
    assert "".join(delta.content or "" for delta in deltas) == "ok"
    await client.aclose()
