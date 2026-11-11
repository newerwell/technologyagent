"""P03-T01 model adapter: token/tool delta, no usage, provider error/timeout."""

from __future__ import annotations

import json

import httpx
import pytest

from backend.app.contracts.agent import ModelMessage
from backend.app.contracts.common import RequestContext
from backend.app.integrations.model import ModelProviderError, OpenAICompatibleModel
from backend.app.ports.tools import ToolSpec
from backend.app.agent.budget import RunBudget
from backend.app.services.model_observation import collect_model_response


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
async def test_cache_usage_survives_adapter_observer_and_cache_summary():
    import importlib

    body = _sse(
        {"choices": [{"delta": {"content": "ok"}}]},
        {"choices": [], "usage": {
            "prompt_tokens": 100,
            "prompt_cache_hit_tokens": 80,
            "prompt_cache_miss_tokens": 20,
        }},
    )

    async def handler(request):
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleModel(
        base_url="http://model.local/v1", model="deepseek-test", api_key="k", http_client=client,
    )
    events = []

    async def emit(kind, payload):
        events.append({"type": kind, "run_id": "run-1", "payload": payload})

    await collect_model_response(
        model, [ModelMessage(role="user", content="hello")], [],
        RequestContext("owner", "request", run_id="run-1"), RunBudget("run-1"), emit,
        purpose="agent_step", prompt_template_id="ta-v2-base-1",
    )
    summary_fn = getattr(
        importlib.import_module("backend.app.services.cache_metrics"),
        "summarize_cache_events",
    )
    cache = summary_fn(events, expected_model_calls=1)

    started = next(event["payload"] for event in events if event["type"] == "model_started")
    finished = next(event["payload"] for event in events if event["type"] == "model_finished")
    assert started["model_name"] == "deepseek-test"
    assert started["prompt_template_id"] == "ta-v2-base-1"
    assert finished["usage"]["prompt_cache_hit_tokens"] == 80
    assert finished["first_output_ms"] >= 0
    assert cache["known_hit_rate"] == 0.8
    await client.aclose()


@pytest.mark.asyncio
async def test_authorized_tool_payload_and_toolset_id_ignore_discovery_order():
    requests = []
    response = _sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]})

    async def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=response, headers={"content-type": "text/event-stream"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleModel(
        base_url="http://model.local/v1", model="deepseek-test", api_key="k", http_client=client,
    )
    alpha = ToolSpec("alpha", "Alpha tool", {
        "type": "object",
        "properties": {"warehouse_id": {"type": "string"}, "page": {"type": "integer"}},
        "required": ["warehouse_id"],
    })
    zeta = ToolSpec("zeta", "Zeta tool", {
        "required": ["part_id"],
        "properties": {"quantity": {"type": "integer"}, "part_id": {"type": "string"}},
        "type": "object",
    })
    first_order = [zeta, alpha]
    second_order = [
        ToolSpec("alpha", "Alpha tool", {
            "required": ["warehouse_id"],
            "properties": {"page": {"type": "integer"}, "warehouse_id": {"type": "string"}},
            "type": "object",
        }),
        ToolSpec("zeta", "Zeta tool", {
            "type": "object",
            "properties": {"part_id": {"type": "string"}, "quantity": {"type": "integer"}},
            "required": ["part_id"],
        }),
    ]
    events = []

    async def emit(kind, payload):
        events.append((kind, payload))

    try:
        for tools in (first_order, second_order, [second_order[0]]):
            await collect_model_response(
                model, [ModelMessage(role="user", content="read only")], tools,
                RequestContext("owner", "request", run_id="run"), RunBudget("run"), emit,
                purpose="agent_step",
            )
        started = [payload for kind, payload in events if kind == "model_started"]
        assert requests[0]["tools"] == requests[1]["tools"]
        assert [item["function"]["name"] for item in requests[0]["tools"]] == ["alpha", "zeta"]
        assert started[0]["toolset_id"] == started[1]["toolset_id"]
        assert isinstance(started[0]["toolset_id"], str)
        assert model.toolset_id_for(first_order) == started[0]["toolset_id"]
        assert [item["function"]["name"] for item in requests[2]["tools"]] == ["alpha"]
        assert started[2]["toolset_id"] != started[0]["toolset_id"]
        assert "authorization" not in json.dumps(requests[0]["tools"]).lower()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_toolset_id_changes_with_schema_and_empty_toolset_is_stable():
    async def handler(request):
        return httpx.Response(200, content=_sse({
            "choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}],
        }), headers={"content-type": "text/event-stream"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleModel(
        base_url="http://model.local/v1", model="m", api_key="k", http_client=client,
    )
    base = ToolSpec("inventory_page", "Page inventory", {"type": "object", "properties": {}})
    changed_description = ToolSpec("inventory_page", "Page stock", base.input_schema)
    changed_schema = ToolSpec("inventory_page", base.description, {
        "type": "object", "properties": {"page": {"type": "integer"}},
    })

    try:
        empty_id = model.toolset_id_for([])
        assert empty_id == model.toolset_id_for([])
        assert empty_id.startswith("sha256:")
        assert model.toolset_id_for([base]) != model.toolset_id_for([changed_description])
        assert model.toolset_id_for([base]) != model.toolset_id_for([changed_schema])
        assert model.toolset_id_for([base]) != empty_id
    finally:
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


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["length", "content_filter", "error"])
async def test_incomplete_finish_reasons_are_never_reported_as_success(finish_reason):
    async def handler(request):
        body = json.dumps({"choices": [{"delta": {"content": "partial"}, "finish_reason": finish_reason}]}).encode()
        return httpx.Response(200, content=b"data: " + body + b"\n\n", headers={"content-type": "text/event-stream"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleModel(base_url="http://model.local/v1", model="m", api_key="k", http_client=client)
    with pytest.raises(ModelProviderError) as error:
        await _collect(model)
    assert error.value.code == "MODEL_INCOMPLETE"
    await client.aclose()


class _ReadTimeoutBody(httpx.AsyncByteStream):
    def __init__(self):
        self.reads = 0

    async def __aiter__(self):
        self.reads += 1
        raise httpx.ReadTimeout("diagnostic body stalled")
        yield b""  # pragma: no cover

    async def aclose(self):
        return None


class _BytesBody(httpx.AsyncByteStream):
    def __init__(self, value: bytes):
        self.value = value

    async def __aiter__(self):
        yield self.value

    async def aclose(self):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429, 500])
async def test_http_status_survives_diagnostic_body_timeout_without_retry(status):
    calls = 0
    body = _ReadTimeoutBody()

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status, stream=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleModel(
        base_url="http://model.local/v1", model="m", api_key="api-secret", http_client=client,
    )
    with pytest.raises(ModelProviderError) as error:
        await collect_model_response(
            model, [ModelMessage(role="user", content="hi")], [],
            RequestContext("owner", "request", run_id="run"), RunBudget("run"), None,
            purpose="agent_step",
        )

    assert error.value.code == "MODEL_PROVIDER_ERROR"
    assert error.value.retryable is (status >= 500)
    assert str(status) in str(error.value)
    assert "api-secret" not in str(error.value)
    assert calls == 1
    assert body.reads == 0
    await client.aclose()


@pytest.mark.asyncio
async def test_corrupt_gzip_success_response_is_protocol_error_without_retry():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, stream=_BytesBody(b"not-a-gzip-stream"),
            headers={"content-type": "text/event-stream", "content-encoding": "gzip"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleModel(
        base_url="http://model.local/v1", model="m", api_key="k", http_client=client,
    )
    with pytest.raises(ModelProviderError) as error:
        await collect_model_response(
            model, [ModelMessage(role="user", content="hi")], [],
            RequestContext("owner", "request", run_id="run"), RunBudget("run"), None,
            purpose="agent_step",
        )

    assert error.value.code == "MODEL_PROTOCOL_ERROR"
    assert calls == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_http_status_survives_corrupt_gzip_error_body_without_retry():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            500, stream=_BytesBody(b"not-a-gzip-stream"),
            headers={"content-type": "text/plain", "content-encoding": "gzip"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleModel(
        base_url="http://model.local/v1", model="m", api_key="k", http_client=client,
    )
    with pytest.raises(ModelProviderError) as error:
        await collect_model_response(
            model, [ModelMessage(role="user", content="hi")], [],
            RequestContext("owner", "request", run_id="run"), RunBudget("run"), None,
            purpose="agent_step",
        )

    assert error.value.code == "MODEL_PROVIDER_ERROR"
    assert error.value.retryable is True
    assert "500" in str(error.value)
    assert calls == 1
    await client.aclose()
