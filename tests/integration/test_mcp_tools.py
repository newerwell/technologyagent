"""P03-T02: 真实 Streamable HTTP MCP 进程、9 工具、Bearer 身份与并发隔离。"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from backend.app.config import Settings
from backend.app.contracts.common import RequestContext, SystemClock
from backend.app.integrations.mcp import McpToolClient
from backend.app.repositories.indexes import ensure_indexes
from backend.app.repositories.mcp_tokens import McpTokenRepository
from backend.app.repositories.mongo import MongoResources
from backend.app.services.mcp_tokens import McpTokenService
from backend.app.services.seeding import seed
from tests.integration.conftest import TEST_MONGODB_URI, make_settings


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _token(settings: Settings, run_id: str, owner: str = "local-owner") -> str:
    mongo = await MongoResources.open(settings)
    try:
        return await McpTokenService(McpTokenRepository(mongo), SystemClock()).issue(
            RequestContext(owner_id=owner, request_id="mcp-test", run_id=run_id)
        )
    finally:
        await mongo.close()


@pytest.fixture()
def mcp_server(db_name, mongo_admin):
    settings = make_settings(db_name)
    mongo = MongoResources(settings)
    asyncio.run(_prepare(mongo))
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "MONGODB_URI": TEST_MONGODB_URI,
            "MONGODB_DATABASE": db_name,
            "MCP_PORT": str(port),
            "MODEL_MODE": "fake",
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "mcp_server.server"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            pytest.fail("MCP server did not become healthy")
        yield settings, port
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        if process.stderr is not None:
            process.stderr.close()
        mongo_admin.drop_database(db_name)


async def _prepare(mongo: MongoResources) -> None:
    await mongo.connect()
    try:
        await ensure_indexes(mongo.db)
        await seed(mongo.db, reset=True)
    finally:
        await mongo.close()


@pytest.mark.asyncio
async def test_mcp_lists_nine_tools_and_returns_real_seed_values(mcp_server):
    settings, port = mcp_server
    token = await _token(settings, "run_a")
    client = McpToolClient(f"http://127.0.0.1:{port}/mcp", token)
    try:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == {
            "inventory_page", "inventory_warning", "inventory_get",
            "supplier_query", "supplier_get", "part_search",
            "part_query", "quote_list", "replenishment_preview",
        }
        for tool in tools:
            assert "owner" not in tool.input_schema.get("properties", {})
            assert "run_id" not in tool.input_schema.get("properties", {})
        inventory = await client.call_tool("inventory_page", {"warehouse_id": "W01", "page_size": 50})
        assert inventory.ok
        record = next(item for item in inventory.data["records"] if item["part_id"] == "P001")
        assert (record["available"], record["projected"], record["shortage"]) == (15, 25, 55)
        preview = await client.call_tool("replenishment_preview", {"part_ids": ["P001"], "warehouse_id": "W01"})
        line = preview.data["lines"][0]
        assert (line["shortage"], line["recommended_quote_id"], line["total_cents"]) == (55, "Q02", 60500)
        seven = await client.call_tool(
            "replenishment_preview", {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7}
        )
        line7 = seven.data["lines"][0]
        assert (line7["recommended_quote_id"], line7["total_cents"]) == ("Q01", 66000)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invalid_token_is_rejected(mcp_server):
    settings, port = mcp_server
    client = McpToolClient(f"http://127.0.0.1:{port}/mcp", "not-a-token")
    try:
        result = await client.call_tool("inventory_page", {})
        assert result.ok is False
        assert result.error is not None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_two_run_headers_do_not_cross(mcp_server):
    settings, port = mcp_server
    token_a = await _token(settings, "run_a", "owner-a")
    token_b = await _token(settings, "run_b", "owner-b")
    a = McpToolClient(f"http://127.0.0.1:{port}/mcp", token_a)
    b = McpToolClient(f"http://127.0.0.1:{port}/mcp", token_b)
    try:
        result_a, result_b = await asyncio.gather(
            a.call_tool("inventory_page", {"page_size": 1}),
            b.call_tool("inventory_page", {"page_size": 1}),
        )
        assert result_a.meta["request_id"] == "mcp:run_a"
        assert result_b.meta["request_id"] == "mcp:run_b"
    finally:
        await a.close()
        await b.close()
