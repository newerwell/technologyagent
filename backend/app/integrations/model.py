"""OpenAI-compatible 真实模型适配器；只做协议转换，不直接写 SSE。"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from backend.app.config import Settings
from backend.app.contracts.agent import ModelDelta, ModelMessage, ModelToolCall
from backend.app.contracts.common import RequestContext
from backend.app.ports.tools import ToolSpec

logger = logging.getLogger(__name__)


class ModelProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str = "MODEL_ERROR", retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _message_payload(message: ModelMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in message.tool_calls
        ]
    if message.tool_call_id:
        payload["tool_call_id"] = message.tool_call_id
    if message.name:
        payload["name"] = message.name
    return payload


def _tools_payload(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


class OpenAICompatibleModel:
    """OpenAI-compatible /chat/completions streaming adapter.

    请求超时 60 秒；usage 不存在时只记录 null，不伪造 0。
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url or not model or not api_key:
            raise ModelProviderError("live model requires base_url, model and api key", code="MODEL_NOT_CONFIGURED")
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._http_client = http_client

    @property
    def model_name(self) -> str:
        return self._model

    async def stream(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec],
        ctx: RequestContext,
    ) -> AsyncIterator[ModelDelta]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [_message_payload(message) for message in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = _tools_payload(tools)
            payload["tool_choice"] = "auto"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        started = time.perf_counter()
        usage_seen: dict[str, Any] | None = None
        saw_data = False
        client = self._http_client or httpx.AsyncClient(timeout=httpx.Timeout(self._timeout))
        owns_client = self._http_client is None
        try:
            async with client.stream(
                "POST",
                self._base_url + "/chat/completions",
                json=payload,
                headers=headers,
                timeout=httpx.Timeout(self._timeout),
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")[:500]
                    raise ModelProviderError(
                        f"model provider returned {response.status_code}: {body}",
                        code="MODEL_PROVIDER_ERROR",
                        retryable=response.status_code >= 500,
                    )
                terminal_seen = False
                async for line in response.aiter_lines():
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        terminal_seen = True
                        break
                    saw_data = True
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ModelProviderError("model returned malformed SSE chunk", code="MODEL_PROTOCOL_ERROR") from exc
                    usage = chunk.get("usage")
                    if isinstance(usage, dict):
                        usage_seen = usage
                        yield ModelDelta(kind="usage", usage=usage)
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    if choices[0].get("finish_reason") is not None:
                        terminal_seen = True
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield ModelDelta(kind="token", content=str(content))
                    for raw in delta.get("tool_calls") or []:
                        function = raw.get("function") or {}
                        yield ModelDelta(
                            kind="tool_call",
                            tool_call=ModelToolCall(
                                id=str(raw.get("id") or ""),
                                name=str(function.get("name") or ""),
                                arguments=str(function.get("arguments") or ""),
                                index=int(raw.get("index", 0)),
                            ),
                        )
            if not saw_data or not terminal_seen:
                raise ModelProviderError(
                    "model stream ended before a terminal marker", code="MODEL_PROTOCOL_ERROR"
                )
        except httpx.TimeoutException as exc:
            raise ModelProviderError("model request timed out", code="MODEL_TIMEOUT", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ModelProviderError(f"model transport failed: {type(exc).__name__}", code="MODEL_UNAVAILABLE", retryable=True) from exc
        finally:
            if owns_client:
                await client.aclose()
            logger.info(
                "model request model=%s duration_ms=%.1f usage_present=%s",
                self._model,
                (time.perf_counter() - started) * 1000,
                usage_seen is not None,
            )


def build_model(settings: Settings) -> OpenAICompatibleModel | None:
    if settings.model_mode != "live":
        return None
    if not settings.model_configured:
        return None
    assert settings.model_api_key is not None
    return OpenAICompatibleModel(
        base_url=settings.model_base_url,
        model=settings.model_name,
        api_key=settings.model_api_key.get_secret_value(),
    )
