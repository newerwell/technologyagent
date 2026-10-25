"""P03 MCP 客户端：每 run 独立 client/header，工具列表转换与调用。"""

from __future__ import annotations

import json
import socket
from collections.abc import Callable
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from backend.app.agent.budget import RunBudget
from backend.app.contracts.common import RequestContext
from backend.app.ports.tools import ToolSpec, ToolResult
from backend.app.services.mcp_tokens import McpTokenService
from mcp_server.tools.specs import ALL_TOOL_SPECS


def _tool_schema(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "input_schema", None)
    if schema is None:
        schema = getattr(tool, "inputSchema", None)
    return schema or {"type": "object", "properties": {}}


def _unwrap(result: Any) -> dict[str, Any]:
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data
    content = getattr(result, "content", None) or []
    for item in content:
        text = getattr(item, "text", None)
        if text:
            try:
                parsed = json.loads(text)
            except ValueError:
                return {"ok": False, "error": {"code": "MCP_PROTOCOL_ERROR", "message": text[:300]}}
            if isinstance(parsed, dict):
                return parsed
    return {"ok": False, "error": {"code": "MCP_EMPTY_RESULT", "message": "MCP returned no data"}}


class McpToolClient:
    def __init__(self, url: str, token: str, *, timeout: float = 15.0) -> None:
        self._url = url
        self._token = token
        self._timeout = timeout
        self._client: Client | None = None

    async def _get_client(self) -> Client:
        if self._client is None:
            transport = StreamableHttpTransport(
                self._url, headers={"Authorization": f"Bearer {self._token}"}
            )
            self._client = Client(transport, timeout=self._timeout)
            try:
                await self._client.__aenter__()
            except BaseException:
                client, self._client = self._client, None
                try:
                    await client.__aexit__(None, None, None)
                except BaseException:
                    pass
                raise
        return self._client

    async def list_tools(self) -> list[ToolSpec]:
        client = await self._get_client()
        tools = await client.list_tools()
        declared = {spec.name: spec for spec in ALL_TOOL_SPECS}
        return [
            ToolSpec(
                name=tool.name,
                description=declared[tool.name].description if tool.name in declared else (tool.description or ""),
                input_schema=_tool_schema(tool),
                effect=declared[tool.name].effect if tool.name in declared else "unsupported",
                capability=declared[tool.name].capability if tool.name in declared else "unknown",
            )
            for tool in tools if tool.name in declared
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any], *, call_id: str = "") -> ToolResult:
        client = await self._get_client()
        try:
            raw = await client.call_tool(name, arguments)
            payload = _unwrap(raw)
            ok = bool(payload.get("ok"))
            error = payload.get("error")
            meta = payload.get("meta") or {}
            return ToolResult(
                ok=ok,
                data=payload.get("data"),
                error=error,
                meta=meta,
                call_id=call_id,
            )
        except Exception as exc:  # noqa: BLE001 - MCP 异常要反馈给模型而不是伪装成功
            return ToolResult(
                ok=False,
                error={"code": "MCP_UNAVAILABLE", "message": f"{type(exc).__name__}: {exc}", "retryable": True},
                meta={},
                call_id=call_id,
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None


class McpToolRegistry:
    def __init__(self, client: McpToolClient, specs: list[ToolSpec], token: str) -> None:
        self._client = client
        self._specs = specs
        self._token = token

    def available(self, ctx: RequestContext) -> list[ToolSpec]:
        return [spec for spec in self._specs if spec.effect != "unsupported"]

    async def invoke(
        self, name: str, arguments: dict[str, Any], ctx: RequestContext, budget: RunBudget
    ) -> ToolResult:
        if name not in {spec.name for spec in self._specs}:
            return ToolResult(
                ok=False,
                error={"code": "UNKNOWN_TOOL", "message": f"tool is not registered: {name}"},
                call_id=ctx.call_id or "",
            )
        return await self._client.call_tool(name, arguments, call_id=ctx.call_id or "")

    async def close(self) -> None:
        await self._client.close()


class McpRegistryFactory:
    """为每个 run 签发独立短期 token 与 client，禁止共享全局 header。"""

    def __init__(self, url: str, tokens: McpTokenService) -> None:
        self._url = url
        self._tokens = tokens

    async def __call__(self, ctx: RequestContext) -> McpToolRegistry:
        token = await self._tokens.issue(ctx)
        client = McpToolClient(self._url, token)
        try:
            specs = await client.list_tools()
        except BaseException:
            try:
                await client.close()
            except BaseException:
                pass
            raise
        return McpToolRegistry(client, specs, token)


def mcp_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
