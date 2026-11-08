"""P09 R7: Exercise all reference tools over the real Streamable HTTP MCP wire."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports.http import StreamableHttpTransport

from backend.app.contracts.common import AppError, RequestContext, SystemClock
from backend.app.contracts.order_workflow import ResumeRequest
from backend.app.repositories.mongo import MongoResources
from backend.app.services.approvals import ApprovalService
from tests.integration.test_mcp_tools import _token, mcp_server
from mcp_server.tools.specs import P08_REFERENCE_TOOL_NAMES


READ_CALLS = {
    "supplier_query": {"name": "供应", "page": 1, "page_size": 5},
    "supplier_page": {"payload": {"name": None, "page": 1, "page_size": 5}},
    "supplier_get": {"supplier_id": "S01"},
    "part_query": {"part_id": "P001"},
    "part_search": {"name": "刹车片", "page": 1, "page_size": 5},
    "part_by_supplier": {"payload": {"supplier_id": "S01", "page": 1, "page_size": 5}},
    "part_page": {"payload": {"name": None, "page": 1, "page_size": 5}},
    "order_page": {"page": 1, "page_size": 5},
    "order_search_details": {"payload": {"status": "submitted", "page": 1, "page_size": 5}},
    "order_statistics": {"payload": {}},
    "inventory_warning": {"page": 1, "page_size": 5},
    "inventory_page": {"warehouse_id": "W01", "page": 1, "page_size": 5},
    "inventory_check": {"payload": {"inventory_id": "I001"}},
    "inventory_get": {"inventory_id": "I001"},
}

READ_NEGATIVE_CALLS = {
    "supplier_query": {"name": "__missing_supplier__", "page": 1, "page_size": 5},
    "supplier_page": {"payload": {"name": "__missing_supplier__", "page": 1, "page_size": 5}},
    "supplier_get": {"supplier_id": "__missing_supplier__"},
    "part_query": {"part_id": "__missing_part__"},
    "part_search": {"name": "__missing_part__", "page": 1, "page_size": 5},
    "part_by_supplier": {"payload": {"supplier_id": "__missing_supplier__", "page": 1, "page_size": 5}},
    "part_page": {"payload": {"name": "__missing_part__", "page": 1, "page_size": 5}},
    "order_page": {"page": 999999, "page_size": 5},
    "order_search_details": {"payload": {"status": "__invalid_status__", "page": 1, "page_size": 5}},
    "order_statistics": {"payload": {}},  # aggregate has no entity selector; this is its only valid empty filter.
    "order_get": {"order_id": "__missing_order__"},
    "inventory_warning": {"warehouse_id": "__missing_warehouse__", "page": 1, "page_size": 5},
    "inventory_page": {"warehouse_id": "__missing_warehouse__", "page": 1, "page_size": 5},
    "inventory_check": {"payload": {"inventory_id": "__missing_inventory__"}},
    "inventory_get": {"inventory_id": "__missing_inventory__"},
}

MALFORMED_WIRE_CALLS = {
    "supplier_query": {"page": "invalid-int"},
    "supplier_page": {"payload": []},
    "supplier_get": {"supplier_id": 123},
    "supplier_create": {"payload": []},
    "supplier_update_status": {"payload": []},
    "part_query": {"part_id": []},
    "part_search": {"page_size": "invalid-int"},
    "part_by_supplier": {"payload": []},
    "part_page": {"payload": []},
    "part_create": {"payload": []},
    "order_create": {"draft_id": [], "approval_id": [], "idempotency_key": []},
    "order_update": {"payload": []},
    "order_page": {"page": "invalid-int"},
    "order_get": {"order_id": 123},
    "order_search_details": {"payload": []},
    "order_statistics": {"payload": []},
    "order_update_status": {"payload": []},
    "inventory_warning": {"page_size": "invalid-int"},
    "inventory_page": {"page": "invalid-int"},
    "inventory_check": {"payload": []},
    "inventory_inbound": {"payload": []},
    "inventory_outbound": {"payload": []},
    "inventory_get": {"inventory_id": []},
}


async def _services(settings):
    mongo = await MongoResources.open(settings)
    return mongo, ApprovalService(mongo, SystemClock())


@pytest.mark.asyncio
async def test_all_reference_reads_accept_and_reject_on_real_mcp_wire(mcp_server):
    """The invalid input must cross HTTP and reach FastMCP validation, not jsonschema locally."""
    from backend.app.integrations.mcp import McpToolClient
    settings, port = mcp_server
    token = await _token(settings, "r7-reads")
    client = McpToolClient(f"http://127.0.0.1:{port}/mcp", token, timeout=30)
    mongo, _ = await _services(settings)

    async def db_facts():
        return {name: await mongo.db[name].count_documents({}) for name in (
            "suppliers", "parts", "orders", "inventories", "inventory_movements", "operations", "approvals"
        )}

    try:
        before = await db_facts()
        order_page = await client.call_tool("order_page", READ_CALLS["order_page"])
        assert order_page.ok and order_page.data["records"]
        calls = {**READ_CALLS, "order_get": {"order_id": order_page.data["records"][0]["id"]}}
        for name, arguments in calls.items():
            result = await client.call_tool(name, arguments)
            assert result.ok, (name, result.error)
            # This negative business lookup crosses Streamable HTTP and reaches the
            # server. List tools with no entity selector return an empty page; get
            # tools return a not-found envelope.
            negative = await client.call_tool(name, READ_NEGATIVE_CALLS[name])
            if name in {"supplier_get", "part_query", "inventory_check", "inventory_get", "order_get",
                        "order_search_details"}:
                assert not negative.ok, (name, negative)
            elif name == "order_statistics":
                assert negative.ok and negative.data["scope_complete"] is True
            else:
                assert negative.ok and negative.data["records"] == [], (name, negative.data)
        assert await db_facts() == before
    finally:
        await client.close()
        await mongo.close()


@pytest.mark.asyncio
async def test_all_23_reference_tools_reject_malformed_inputs_on_raw_streamable_http(
    mcp_server, mongo_admin
):
    """Malformed arguments must reach and fail in the registered MCP server, not local JSON Schema."""
    from tests.integration.test_mcp_tools import _token

    settings, port = mcp_server
    token = await _token(settings, "p09-c04-malformed")
    health_url = f"http://127.0.0.1:{port}/health"
    transport = StreamableHttpTransport(f"http://127.0.0.1:{port}/mcp",
                                        headers={"Authorization": f"Bearer {token}"})
    db = mongo_admin[settings.mongodb_database]
    watched = ("suppliers", "parts", "orders", "inventories", "inventory_movements", "operations", "approvals")

    def collection_facts():
        return {name: list(db[name].find({}).sort("_id", 1)) for name in watched}

    assert httpx.get(health_url, timeout=3).status_code == 200
    before = collection_facts()
    async with Client(transport, timeout=10) as client:
        tools = await client.list_tools()
        wire_names = {tool.name for tool in tools}
        assert wire_names.intersection(MALFORMED_WIRE_CALLS) == set(P08_REFERENCE_TOOL_NAMES)
        assert len(MALFORMED_WIRE_CALLS) == len(P08_REFERENCE_TOOL_NAMES) == 23
        wire_schema = {tool.name: tool.input_schema for tool in tools}
        null_result = await client.call_tool("supplier_page", {"payload": None}, timeout=5, raise_on_error=False)
        assert null_result.is_error is True, "null payload must not become a successful unfiltered query"
        for name, arguments in MALFORMED_WIRE_CALLS.items():
            assert name in wire_schema
            # call_tool sends the raw argument object and returns the server's
            # is_error/content fields without McpToolClient's MCP_UNAVAILABLE wrapper.
            try:
                result = await client.call_tool(name, arguments, timeout=5, raise_on_error=False)
            except Exception as exc:
                raise AssertionError(f"{name}: malformed input did not yield a server validation error") from exc
            assert result.is_error is True, (name, arguments, result)
            message = " ".join(item.text for item in result.content if getattr(item, "text", None))
            assert any(token in message.lower() for token in (
                "valid", "invalid", "required", "field", "argument", "schema", "input",
            )), (name, arguments, message)
            print(json.dumps({"tool": name, "arguments": arguments, "error": message}, ensure_ascii=False))
    assert collection_facts() == before
    assert httpx.get(health_url, timeout=3).status_code == 200


@pytest.mark.asyncio
async def test_all_eight_reference_writes_are_approved_idempotent_owner_scoped_and_versioned(
    mcp_server, mongo_admin
):
    """Exercise all eight P08 write tools over actual MCP and verify per-action DB effects."""
    from backend.app.integrations.mcp import McpToolClient

    settings, port = mcp_server
    owner = "local-owner"
    ctx = RequestContext(owner_id=owner, request_id="r7-write-matrix", run_id="r7-write-matrix")
    token = await _token(settings, ctx.run_id, owner)
    wrong_owner_token = await _token(settings, ctx.run_id + "-wrong-owner", "r7-wrong-owner")
    client = McpToolClient(f"http://127.0.0.1:{port}/mcp", token, timeout=60)
    wrong_owner = McpToolClient(f"http://127.0.0.1:{port}/mcp", wrong_owner_token, timeout=60)
    mongo, approvals = await _services(settings)
    db = mongo.db
    await db.runs.insert_one({"_id": ctx.run_id, "owner_id": owner, "status": "running",
                              "cancel_requested": False, "commit_fence": 0})
    before = {
        "suppliers": await db.suppliers.count_documents({}),
        "parts": await db.parts.count_documents({}),
        "orders": await db.orders.count_documents({"owner_id": owner}),
        "movements": await db.inventory_movements.count_documents({}),
        "inventory": await db.inventories.find_one({"_id": "I001"}),
    }

    async def prepared(action: str, payload: dict, key: str):
        proposal = await client.call_tool("mutation_prepare", {"action": action, "payload": payload})
        assert proposal.ok, (action, proposal.error)
        approval_id = proposal.data["approval_id"]
        # A stale decision version is rejected before the valid explicit approval.
        with pytest.raises(AppError) as stale:
            await approvals.resolve_mutation(approval_id, "approve", key + "-stale", ctx, expected_version=2)
        assert stale.value.code == "IDEMPOTENCY_CONFLICT"
        await approvals.resolve_mutation(approval_id, "approve", key + "-decision", ctx, expected_version=1)
        return approval_id

    async def execute(name: str, payload: dict, approval_id: str, key: str):
        args = {"payload": payload, "approval_id": approval_id, "idempotency_key": key}
        denied = await wrong_owner.call_tool(name, args)
        assert not denied.ok, (name, "wrong owner was accepted", denied)
        direct = await client.call_tool(name, {"payload": payload})
        assert not direct.ok, (name, "unapproved call was accepted", direct)
        first = await client.call_tool(name, args)
        assert first.ok, (name, first.error)
        replay = await client.call_tool(name, args)
        assert replay.ok and replay.data == first.data, (name, first.data, replay.data)
        operation = await db.operations.find_one({"owner_id": owner, "idempotency_key": key})
        assert operation and operation["status"] == "succeeded", (name, operation)
        return first.data

    try:
        # supplier_create
        p = {"code": "R7-SUP-NEW", "name": "R7供应商"}
        a = await prepared("supplier_create", p, "r7-supplier-create")
        sup = await execute("supplier_create", p, a, "r7-supplier-create")
        assert await db.suppliers.count_documents({"code": p["code"]}) == 1
        assert before["suppliers"] == 3

        # supplier_update_status
        p = {"supplier_id": "S03", "status": "active"}
        a = await prepared("supplier_update_status", p, "r7-supplier-status")
        await execute("supplier_update_status", p, a, "r7-supplier-status")
        assert (await db.suppliers.find_one({"_id": "S03"}))["status"] == "active"

        # part_create
        p = {"code": "R7-PART-NEW", "name": "R7测试件", "unit": "件"}
        a = await prepared("part_create", p, "r7-part-create")
        await execute("part_create", p, a, "r7-part-create")
        assert await db.parts.count_documents({"code": p["code"]}) == 1
        assert before["parts"] == 6

        # order_create uses the existing P04 draft + approval path (not generic mutation_prepare).
        draft_result = await client.call_tool("draft_prepare", {"part_ids": ["P001"], "warehouse_id": "W01"})
        assert draft_result.ok, draft_result.error
        draft_id = draft_result.data["drafts"][0]["id"]
        order_approval = await approvals.request(draft_id, ctx.run_id, ctx)
        await approvals.resolve(order_approval["approval_id"], ResumeRequest(
            interrupt_id=order_approval["approval_id"], decision="approve",
            idempotency_key="r7-order-decision"), ctx)
        order_args = {"draft_id": draft_id, "approval_id": order_approval["approval_id"],
                      "idempotency_key": "r7-order-create"}
        assert not (await wrong_owner.call_tool("order_create", order_args)).ok
        created_order = await client.call_tool("order_create", order_args)
        replay_order = await client.call_tool("order_create", order_args)
        assert created_order.ok and replay_order.ok and created_order.data == replay_order.data
        assert await db.orders.count_documents({"owner_id": owner}) == before["orders"] + 1
        created_inventory = await db.inventories.find_one({"_id": "I001"})
        assert (created_inventory["inbound"], created_inventory["on_hand"]) == (65, 20)
        assert (await db.approvals.find_one({"_id": order_approval["approval_id"]}))["status"] == "consumed"

        # Remaining five writes, each backed by a distinct approval and persistent operation.
        order = await db.orders.find_one({"_id": "O001", "owner_id": owner, "status": "submitted"})
        quote_id = "Q01"
        amendment = {"order_id": order["_id"], "expected_version": order["version"],
                     "items": [{"part_id": "P001", "quote_id": quote_id, "quantity": 56}]}
        a = await prepared("order_update", amendment, "r7-order-update")
        await execute("order_update", amendment, a, "r7-order-update")
        amended = await db.orders.find_one({"_id": "O001", "owner_id": owner})
        assert (amended["items"][0]["quantity"], amended["total_cents"], amended["version"]) == (56, 67200, 2)
        assert (await db.inventories.find_one({"_id": "I001"}))["inbound"] == 111
        stale_amendment = {**amendment, "expected_version": order["version"]}
        a_stale = await prepared("order_update", stale_amendment, "r7-order-update-stale")
        stale_result = await client.call_tool("order_update", {
            "payload": stale_amendment, "approval_id": a_stale, "idempotency_key": "r7-order-update-stale"})
        assert not stale_result.ok and "stale" in str(stale_result.error).lower()

        order = await db.orders.find_one({"_id": "O001", "owner_id": owner})
        status_change = {"order_id": order["_id"], "status": "shipped", "expected_version": order["version"]}
        a = await prepared("order_update_status", status_change, "r7-order-status")
        await execute("order_update_status", status_change, a, "r7-order-status")

        inv = await db.inventories.find_one({"_id": "I001"})
        inbound = {"inventory_id": "I001", "quantity": 1, "expected_version": inv["version"]}
        a = await prepared("inventory_inbound", inbound, "r7-inbound")
        await execute("inventory_inbound", inbound, a, "r7-inbound")

        inv = await db.inventories.find_one({"_id": "I001"})
        stale_outbound = {"inventory_id": "I001", "quantity": 1, "expected_version": inv["version"] - 1}
        stale_approval = await prepared("inventory_outbound", stale_outbound, "r7-outbound-stale")
        stale_result = await client.call_tool("inventory_outbound", {
            "payload": stale_outbound, "approval_id": stale_approval,
            "idempotency_key": "r7-outbound-stale"})
        assert not stale_result.ok and "stale" in str(stale_result.error).lower()
        after_stale = await db.inventories.find_one({"_id": "I001"})
        assert after_stale["on_hand"] == inv["on_hand"] and after_stale["version"] == inv["version"]

        inv = await db.inventories.find_one({"_id": "I001"})
        outbound = {"inventory_id": "I001", "quantity": 1, "expected_version": inv["version"]}
        a = await prepared("inventory_outbound", outbound, "r7-outbound")
        await execute("inventory_outbound", outbound, a, "r7-outbound")

        final_inventory = await db.inventories.find_one({"_id": "I001"})
        assert final_inventory["on_hand"] == before["inventory"]["on_hand"]
        assert final_inventory["inbound"] == 111
        # The order commit and amendment also reconcile inbound/version; the
        # standalone receipt and outbound each add one further version.
        assert final_inventory["version"] == before["inventory"]["version"] + 4
        assert await db.inventory_movements.count_documents({}) == before["movements"] + 2
        write_operations = await db.operations.find(
            {"owner_id": owner, "idempotency_key": {"$in": ["r7-inbound", "r7-outbound"]}},
            {"_id": 1},
        ).to_list(length=2)
        deltas = await db.inventory_movements.find(
            {"operation_id": {"$in": [op["_id"] for op in write_operations]}},
            {"on_hand_delta": 1},
        ).to_list(length=10)
        assert sorted(item["on_hand_delta"] for item in deltas) == [-1, 1]
        assert await db.operations.count_documents({"owner_id": owner, "status": "succeeded"}) == 8
        assert sup["code"] == "R7-SUP-NEW"
    finally:
        await client.close()
        await wrong_owner.close()
        await mongo.close()
