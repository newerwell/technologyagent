"""P08 generic proposal approval, transaction, version and outbound guards."""

import asyncio

from pymongo import MongoClient

from backend.app.contracts.common import AppError, RequestContext


def _run(client, awaitable):
    async def invoke():
        return await awaitable
    return client.portal.call(invoke)


def _proposal(client, action, payload, key):
    ctx = RequestContext("local-owner", "p08-business", run_id="p08-business")
    approvals = client.app.state.container.approvals
    service = client.app.state.container.business_mutations
    proposal = _run(client, approvals.request_mutation(action, payload, ctx))
    try:
        _run(client, service.execute(proposal["approval_id"], key, ctx, expected_action=action))
        assert False, "unapproved proposal must not mutate business data"
    except AppError as exc:
        assert exc.code == "APPROVAL_REQUIRED"
    return ctx, proposal


def test_supplier_create_requires_approval_and_replays_one_result(seeded_client):
    payload = {"code": "SUP-P08", "name": "P08 测试供应商"}
    ctx, proposal = _proposal(seeded_client, "supplier_create", payload, "supplier-create")
    container = seeded_client.app.state.container
    _run(seeded_client, container.approvals.resolve_mutation(proposal["approval_id"], "approve", "supplier-approve", ctx))
    result = _run(seeded_client, container.business_mutations.execute(proposal["approval_id"], "supplier-create", ctx,
                                                                      expected_action="supplier_create"))
    replay = _run(seeded_client, container.business_mutations.execute(proposal["approval_id"], "supplier-create", ctx,
                                                                      expected_action="supplier_create"))
    assert result == replay
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        assert sync[container.settings.mongodb_database].suppliers.count_documents({"code": "SUP-P08"}) == 1
        assert sync[container.settings.mongodb_database].approvals.find_one({"_id": proposal["approval_id"]})["status"] == "consumed"
    finally:
        sync.close()


def test_submitted_order_cancel_reconciles_inbound_and_stale_version_is_rejected(seeded_client):
    prepared = seeded_client.post("/api/drafts", json={"part_ids": ["P001"], "warehouse_id": "W01",
                                                       "max_lead_days": 7}).json()["data"]["drafts"][0]
    approval_id = seeded_client.post(f"/api/drafts/{prepared['id']}/approval", json={"run_id": "cancel-p08"}).json()["data"]["approval_id"]
    assert seeded_client.post(f"/api/approvals/{approval_id}/resolve", json={"interrupt_id": "i", "decision": "approve",
        "expected_version": 1, "idempotency_key": "approve-cancel-p08"}).status_code == 200
    order = seeded_client.post("/api/orders/create", json={"draft_id": prepared["id"], "approval_id": approval_id,
        "idempotency_key": "create-cancel-p08"}).json()["data"]["order"]
    container = seeded_client.app.state.container
    ctx, stale = _proposal(seeded_client, "order_update_status", {"order_id": order["id"], "status": "cancelled",
        "expected_version": 99}, "cancel-stale")
    _run(seeded_client, container.approvals.resolve_mutation(stale["approval_id"], "approve", "cancel-stale-decision", ctx))
    try:
        _run(seeded_client, container.business_mutations.execute(stale["approval_id"], "cancel-stale", ctx,
                                                               expected_action="order_update_status"))
        assert False, "stale version must fail"
    except AppError as exc:
        assert exc.code == "IDEMPOTENCY_CONFLICT"
    fresh_payload = {"order_id": order["id"], "status": "cancelled", "expected_version": 1}
    ctx2 = RequestContext("local-owner", "p08-business", run_id="p08-business")
    proposal = _run(seeded_client, container.approvals.request_mutation("order_update_status", fresh_payload, ctx2))
    _run(seeded_client, container.approvals.resolve_mutation(proposal["approval_id"], "approve", "cancel-fresh", ctx2))
    _run(seeded_client, container.business_mutations.execute(proposal["approval_id"], "cancel-fresh", ctx2,
                                                              expected_action="order_update_status"))
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        db = sync[container.settings.mongodb_database]
        assert db.orders.find_one({"_id": order["id"]})["status"] == "cancelled"
        assert db.inventories.find_one({"_id": "I001"})["inbound"] == 10
    finally:
        sync.close()


def test_submitted_order_amendment_reprices_and_adjusts_inbound_under_approval(seeded_client):
    prepared = seeded_client.post("/api/drafts", json={"part_ids": ["P001"], "warehouse_id": "W01",
                                                       "max_lead_days": 7}).json()["data"]["drafts"][0]
    approval_id = seeded_client.post(f"/api/drafts/{prepared['id']}/approval", json={"run_id": "amend-p08"}).json()["data"]["approval_id"]
    seeded_client.post(f"/api/approvals/{approval_id}/resolve", json={"interrupt_id": "i", "decision": "approve",
        "expected_version": 1, "idempotency_key": "approve-amend-p08"})
    order = seeded_client.post("/api/orders/create", json={"draft_id": prepared["id"], "approval_id": approval_id,
        "idempotency_key": "create-amend-p08"}).json()["data"]["order"]
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", "p08-business", run_id="p08-business")
    payload = {"order_id": order["id"], "expected_version": 1,
               "items": [{"part_id": "P001", "quote_id": "Q01", "quantity": 50}]}
    proposal = _run(seeded_client, container.approvals.request_mutation("order_update", payload, ctx))
    _run(seeded_client, container.approvals.resolve_mutation(proposal["approval_id"], "approve", "amend-decision", ctx))
    result = _run(seeded_client, container.business_mutations.execute(proposal["approval_id"], "amend-order", ctx,
                                                                      expected_action="order_update"))
    assert (result["version"], result["total_cents"], result["items"][0]["quantity"]) == (2, 60000, 50)
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        db = sync[container.settings.mongodb_database]
        assert db.inventories.find_one({"_id": "I001"})["inbound"] == 60
        assert db.orders.find_one({"_id": order["id"]})["version"] == 2
    finally:
        sync.close()


def test_supplier_part_and_manual_inventory_writes_are_approved_and_duplicate_codes_fail(seeded_client):
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", "p08-write-matrix", run_id="p08-write-matrix")

    def execute(action, payload, key):
        proposal = _run(seeded_client, container.approvals.request_mutation(action, payload, ctx))
        _run(seeded_client, container.approvals.resolve_mutation(proposal["approval_id"], "approve", key + "-decision", ctx))
        return _run(seeded_client, container.business_mutations.execute(proposal["approval_id"], key, ctx,
                                                                         expected_action=action))

    supplier = execute("supplier_create", {"code": "P08-SUP", "name": "P08供应商"}, "p08-supplier")
    assert supplier["status"] == "active"
    duplicate_supplier = _run(seeded_client, container.approvals.request_mutation(
        "supplier_create", {"code": "P08-SUP", "name": "重复供应商"}, ctx))
    _run(seeded_client, container.approvals.resolve_mutation(duplicate_supplier["approval_id"], "approve", "p08-duplicate-sup", ctx))
    try:
        _run(seeded_client, container.business_mutations.execute(duplicate_supplier["approval_id"], "p08-duplicate-sup", ctx))
        assert False, "duplicate supplier code must fail"
    except AppError as exc:
        assert exc.code == "IDEMPOTENCY_CONFLICT"

    inactive = execute("supplier_update_status", {"supplier_id": supplier["id"], "status": "inactive"}, "p08-inactive-sup")
    assert inactive["status"] == "inactive"
    part = execute("part_create", {"code": "P08-PART", "name": "P08物料", "unit": "件"}, "p08-part")
    assert part["active"] is True and part["unit"] == "件"
    duplicate_part = _run(seeded_client, container.approvals.request_mutation(
        "part_create", {"code": "P08-PART", "name": "重复物料", "unit": "件"}, ctx))
    _run(seeded_client, container.approvals.resolve_mutation(duplicate_part["approval_id"], "approve", "p08-duplicate-part", ctx))
    try:
        _run(seeded_client, container.business_mutations.execute(duplicate_part["approval_id"], "p08-duplicate-part", ctx))
        assert False, "duplicate part code must fail"
    except AppError as exc:
        assert exc.code == "IDEMPOTENCY_CONFLICT"

    inbound = execute("inventory_inbound", {"inventory_id": "I001", "quantity": 3, "expected_version": 1}, "p08-manual-in")
    outbound = execute("inventory_outbound", {"inventory_id": "I001", "quantity": 4, "expected_version": 2}, "p08-manual-out")
    assert (inbound["on_hand"], inbound["inbound"], outbound["on_hand"], outbound["inbound"]) == (23, 10, 19, 10)
