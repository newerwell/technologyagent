import asyncio

import pytest

from backend.app.contracts.common import RequestContext
from backend.app.integrations import mcp


class Tokens:
    async def issue(self, ctx):
        return "opaque-token"


class Client:
    instances = []
    def __init__(self, url, token):
        self.closed = 0
        self.error = RuntimeError("discovery failed")
        self.instances.append(self)
    async def list_tools(self):
        raise self.error
    async def close(self):
        self.closed += 1
        if getattr(self, "fail_close", False):
            raise RuntimeError("cleanup failed")


@pytest.mark.asyncio
async def test_factory_closes_connected_client_when_discovery_fails(monkeypatch):
    Client.instances.clear()
    monkeypatch.setattr(mcp, "McpToolClient", Client)
    factory = mcp.McpRegistryFactory("http://mcp", Tokens())
    with pytest.raises(RuntimeError, match="discovery failed"):
        await factory(RequestContext(owner_id="owner", request_id="req", run_id="run"))
    assert len(Client.instances) == 1
    assert Client.instances[0].closed == 1


@pytest.mark.asyncio
async def test_factory_preserves_discovery_error_when_cleanup_also_fails(monkeypatch):
    class BrokenClose(Client):
        def __init__(self, url, token):
            self.closed = 0
            self.error = RuntimeError("original discovery error")
            self.fail_close = True
            Client.instances.append(self)
    Client.instances.clear()
    monkeypatch.setattr(mcp, "McpToolClient", BrokenClose)
    factory = mcp.McpRegistryFactory("http://mcp", Tokens())
    with pytest.raises(RuntimeError, match="original discovery error"):
        await factory(RequestContext(owner_id="owner", request_id="req", run_id="run"))
    assert Client.instances[0].closed == 1


@pytest.mark.asyncio
async def test_successful_factory_transfers_cleanup_to_registry(monkeypatch):
    from backend.app.ports.tools import ToolSpec
    class Ready(Client):
        def __init__(self, url, token):
            self.closed = 0
            Client.instances.append(self)
        async def list_tools(self):
            return [ToolSpec("inventory_get", "read", {"type": "object"})]
    Client.instances.clear()
    monkeypatch.setattr(mcp, "McpToolClient", Ready)
    registry = await mcp.McpRegistryFactory("http://mcp", Tokens())(
        RequestContext(owner_id="owner", request_id="req", run_id="run")
    )
    assert Client.instances[0].closed == 0
    await registry.close()
    assert Client.instances[0].closed == 1


@pytest.mark.asyncio
async def test_factory_closes_client_on_cancellation_without_masking_cancel(monkeypatch):
    Client.instances.clear()
    async def cancelled(_self):
        raise asyncio.CancelledError()
    monkeypatch.setattr(mcp, "McpToolClient", Client)
    monkeypatch.setattr(Client, "list_tools", cancelled)
    factory = mcp.McpRegistryFactory("http://mcp", Tokens())
    with pytest.raises(asyncio.CancelledError):
        await factory(RequestContext(owner_id="owner", request_id="req", run_id="run"))
    assert Client.instances[0].closed == 1


@pytest.mark.asyncio
async def test_half_initialized_transport_is_closed_when_enter_fails(monkeypatch):
    instances = []
    class PartialClient:
        def __init__(self):
            self.entered = 0
            self.closed = 0
            instances.append(self)
        async def __aenter__(self):
            self.entered += 1
            raise RuntimeError("connect failed")
        async def __aexit__(self, *_args):
            self.closed += 1
            raise RuntimeError("cleanup failed")
    monkeypatch.setattr(mcp, "StreamableHttpTransport", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(mcp, "Client", lambda *_args, **_kwargs: PartialClient())
    client = mcp.McpToolClient("http://mcp", "opaque-token")
    with pytest.raises(RuntimeError, match="connect failed"):
        await client.list_tools()
    assert client._client is None
    assert instances[0].entered == 1
    assert instances[0].closed == 1
