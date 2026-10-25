"""真实 MCP 进程：P03 的 9 个只读工具与 P04 受审批订单入口。"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from jsonschema import ValidationError, validate
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
from mcp_server.tools.specs import P08_REFERENCE_TOOL_NAMES


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
async def test_mcp_keeps_legacy_tools_and_registers_all_p08_names(mcp_server):
    settings, port = mcp_server
    token = await _token(settings, "run_a")
    client = McpToolClient(f"http://127.0.0.1:{port}/mcp", token)
    try:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        readonly = {
            "inventory_page", "inventory_warning", "inventory_get",
            "supplier_query", "supplier_get", "part_search",
            "part_query", "quote_list", "replenishment_preview",
        }
        from mcp_server.tools.specs import ALL_TOOL_SPECS, P08_REFERENCE_TOOL_NAMES, P08_TOOL_BY_NAME
        assert names == {spec.name for spec in ALL_TOOL_SPECS}
        assert set(P08_REFERENCE_TOOL_NAMES) <= names
        assert len(P08_REFERENCE_TOOL_NAMES) == 23
        assert readonly <= names
        for tool in tools:
            assert "owner" not in tool.input_schema.get("properties", {})
            assert "run_id" not in tool.input_schema.get("properties", {})
        # Verify the actual MCP wire schema, not just the in-process registry.
        # In particular, generic P08 wrappers must not turn typed payloads into
        # arbitrary JSON objects when registered with FastMCP.
        by_name = {tool.name: tool for tool in tools}
        for name, spec in P08_TOOL_BY_NAME.items():
            assert by_name[name].input_schema == spec.input_schema
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
        suppliers = await client.call_tool("supplier_page", {"payload": {"page": 1, "page_size": 20}})
        assert suppliers.ok and suppliers.data["total"] == 3
        by_supplier = await client.call_tool("part_by_supplier", {"payload": {"supplier_id": "S01"}})
        assert by_supplier.ok
        stats = await client.call_tool("order_statistics", {"payload": {}})
        assert stats.ok and stats.data["total"] == 2 and stats.data["scope_complete"] is True
        bad_write = await client.call_tool("supplier_create", {"payload": {"code": "DIRECT", "name": "禁止直写"}})
        assert bad_write.ok is False
        assert bad_write.error["code"] == "APPROVAL_REQUIRED"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_all_23_reference_tools_execute_read_paths_or_fail_closed_for_unapproved_writes(mcp_server, mongo_admin):
    settings, port = mcp_server
    token = await _token(settings, "run_p08_matrix")
    client = McpToolClient(f"http://127.0.0.1:{port}/mcp", token)
    read_calls = {
        "supplier_query": {"name": "供应", "page": 1, "page_size": 5},
        "supplier_page": {"payload": {"page": 1, "page_size": 5}},
        "supplier_get": {"supplier_id": "S01"},
        "part_query": {"part_id": "P001"},
        "part_search": {"name": "刹车片", "page": 1, "page_size": 5},
        "part_by_supplier": {"payload": {"supplier_id": "S01", "page": 1, "page_size": 5}},
        "part_page": {"payload": {"page": 1, "page_size": 5}},
        "order_page": {"page": 1, "page_size": 5},
        "order_search_details": {"payload": {"status": "submitted", "page": 1, "page_size": 5}},
        "order_statistics": {"payload": {}},
        "inventory_warning": {"page": 1, "page_size": 5},
        "inventory_page": {"warehouse_id": "W01", "page": 1, "page_size": 5},
        "inventory_check": {"payload": {"inventory_id": "I001"}},
        "inventory_get": {"inventory_id": "I001"},
    }
    write_calls = {
        "supplier_create": {"payload": {"code": "DIRECT-SUP", "name": "未批准不得新增"}},
        "supplier_update_status": {"payload": {"supplier_id": "S01", "status": "inactive"}},
        "part_create": {"payload": {"code": "DIRECT-PART", "name": "未批准不得新增", "unit": "件"}},
        "order_create": {"draft_id": "missing-draft", "approval_id": "missing-approval", "idempotency_key": "direct-order"},
        "order_update": {"payload": {"order_id": "PO-2026-001", "expected_version": 1,
                                      "items": [{"part_id": "P001", "quote_id": "Q01", "quantity": 1}]}},
        "order_update_status": {"payload": {"order_id": "PO-2026-001", "status": "cancelled", "expected_version": 1}},
        "inventory_inbound": {"payload": {"inventory_id": "I001", "quantity": 1, "expected_version": 1}},
        "inventory_outbound": {"payload": {"inventory_id": "I001", "quantity": 1, "expected_version": 1}},
    }
    try:
        wire_schemas = {tool.name: tool.input_schema for tool in await client.list_tools()}
        assert set(read_calls) | set(write_calls) | {"order_get"} == set(P08_REFERENCE_TOOL_NAMES)
        db = mongo_admin[settings.mongodb_database]
        order_count_before = db.orders.count_documents({})
        inventory_before = db.inventories.find_one({"_id": "I001"}, {"on_hand": 1, "inbound": 1, "version": 1})
        movement_count_before = db.inventory_movements.count_documents({})
        order_page = None
        for name, arguments in read_calls.items():
            result = await client.call_tool(name, arguments)
            assert result.ok, (name, result.error)
            if name == "order_page":
                order_page = result.data
        assert order_page and order_page["records"]
        order_result = await client.call_tool("order_get", {"order_id": order_page["records"][0]["id"]})
        assert order_result.ok, order_result.error
        for name, arguments in write_calls.items():
            result = await client.call_tool(name, arguments)
            assert not result.ok, name
        all_valid_calls = {**read_calls, **write_calls,
                           "order_get": {"order_id": order_page["records"][0]["id"]}}
        for name, arguments in all_valid_calls.items():
            malformed = {**arguments, "unexpected": "must be rejected by the wire schema"}
            with pytest.raises(ValidationError):
                validate(malformed, wire_schemas[name])
        assert db.suppliers.count_documents({"code": "DIRECT-SUP"}) == 0
        assert db.parts.count_documents({"code": "DIRECT-PART"}) == 0
        assert db.orders.count_documents({}) == order_count_before
        inventory_after = db.inventories.find_one({"_id": "I001"}, {"on_hand": 1, "inbound": 1, "version": 1})
        assert {field: inventory_after[field] for field in ("on_hand", "inbound", "version")} == {
            field: inventory_before[field] for field in ("on_hand", "inbound", "version")}
        assert db.inventory_movements.count_documents({}) == movement_count_before
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mcp_order_create_without_approval_has_no_business_or_operation_write(mcp_server, mongo_admin):
    settings, port = mcp_server
    token = await _token(settings, "run_unapproved")
    client = McpToolClient(f"http://127.0.0.1:{port}/mcp", token)
    try:
        prepared = await client.call_tool("draft_prepare", {
            "part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7,
        })
        assert prepared.ok, prepared.error
        draft_id = prepared.data["drafts"][0]["id"]
        result = await client.call_tool("order_create", {
            "draft_id": draft_id, "approval_id": "missing-approval",
            "idempotency_key": "mcp-unapproved",
        })
        assert result.ok is False
        assert result.error is not None
        assert mongo_admin[settings.mongodb_database]["orders"].count_documents({"owner_id": "local-owner"}) == 2
        assert mongo_admin[settings.mongodb_database]["operations"].count_documents(
            {"idempotency_key": "mcp-unapproved"}
        ) == 0
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
