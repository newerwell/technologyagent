"""P08 fixed receipt lifecycle and immutable receipt identity regressions."""

from __future__ import annotations

import asyncio
import pytest

from pymongo import MongoClient

from backend.app.contracts.common import RequestContext


def _run(client, awaitable):
    async def invoke():
        return await awaitable
    return client.portal.call(invoke)


def _submit_p001(seeded_client):
    draft = seeded_client.post("/api/drafts", json={
        "part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7,
    }).json()["data"]["drafts"][0]
    approval_id = seeded_client.post(f"/api/drafts/{draft['id']}/approval", json={"run_id": "p08-test"}).json()["data"]["approval_id"]
    assert seeded_client.post(f"/api/approvals/{approval_id}/resolve", json={
        "interrupt_id": "p08-test", "decision": "approve", "expected_version": 1,
        "idempotency_key": "p08-create-decision",
    }).status_code == 200
    response = seeded_client.post("/api/orders/create", json={
        "draft_id": draft["id"], "approval_id": approval_id, "idempotency_key": "p08-order-55",
    })
    assert response.status_code == 200, response.text
    return response.json()["data"]["order"]


def _approve_receive(seeded_client, payload, approval_id):
    service = seeded_client.app.state.container.approvals
    ctx = RequestContext("local-owner", "p08-test", run_id="p08-test")
    return _run(seeded_client, service.request_mutation("inventory_receive", payload, ctx, proposal_id=approval_id))


def _approve_and_execute(seeded_client, action, payload, key):
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", "p08-test", run_id="p08-test")
    proposal = _run(seeded_client, container.approvals.request_mutation(action, payload, ctx))
    try:
        _run(seeded_client, container.business_mutations.execute(proposal["approval_id"], key, ctx))
        assert False, "direct unapproved mutation must fail"
    except Exception as exc:
        assert getattr(exc, "code", None) == "APPROVAL_REQUIRED"
    _run(seeded_client, container.approvals.resolve_mutation(proposal["approval_id"], "approve", key + "-decision", ctx))
    return _run(seeded_client, container.business_mutations.execute(proposal["approval_id"], key, ctx))


def _receive(seeded_client, order_id, receipt_id, qty, approval_id, key):
    ctx = RequestContext("local-owner", "p08-test", run_id="p08-test")
    payload = {"order_id": order_id, "receipt_id": receipt_id, "warehouse_id": "W01",
               "items": [{"part_id": "P001", "quantity": qty}]}
    _approve_receive(seeded_client, payload, approval_id)
    return _run(seeded_client, seeded_client.app.state.container.inventory_mutations.receive(
        **payload, approval_id=approval_id, idempotency_key=key, ctx=ctx))


def test_p001_receipt_lifecycle_and_operation_swap_cannot_double_receive(seeded_client):
    order = _submit_p001(seeded_client)
    container = seeded_client.app.state.container
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    db = sync[container.settings.mongodb_database]
    _approve_and_execute(seeded_client, "order_update_status", {"order_id": order["id"], "status": "shipped", "expected_version": order["version"]}, "ship-55")
    def stock():
        row = db.inventories.find_one({"_id": "I001"})
        po = db.orders.find_one({"_id": order["id"]})
        return row["inbound"], row["on_hand"], po["items"][0]["received_qty"], po["status"]
    assert stock()[:3] == (65, 20, 0)
    ctx = RequestContext("local-owner", "p08-test", run_id="p08-test")
    first_payload = {"order_id": order["id"], "receipt_id": "R-P08-20", "warehouse_id": "W01",
                     "items": [{"part_id": "P001", "quantity": 20}]}
    approval1 = _run(seeded_client, container.approvals.request_mutation("inventory_receive", first_payload, ctx, proposal_id="proposal-r1"))["approval_id"]
    _run(seeded_client, container.approvals.resolve_mutation(approval1, "approve", "dec-r1", ctx))
    result = _run(seeded_client, container.inventory_mutations.receive(**first_payload, approval_id=approval1,
        idempotency_key="receive-20-a", ctx=ctx))
    assert stock()[:3] == (45, 40, 20)
    replay = _run(seeded_client, container.inventory_mutations.receive(**first_payload, approval_id=approval1,
        idempotency_key="receive-20-different-operation", ctx=ctx))
    assert replay == result
    assert stock()[:3] == (45, 40, 20)
    second_payload = {"order_id": order["id"], "receipt_id": "R-P08-35", "warehouse_id": "W01",
                      "items": [{"part_id": "P001", "quantity": 35}]}
    approval2 = _run(seeded_client, container.approvals.request_mutation("inventory_receive", second_payload, ctx, proposal_id="proposal-r2"))["approval_id"]
    _run(seeded_client, container.approvals.resolve_mutation(approval2, "approve", "dec-r2", ctx))
    _run(seeded_client, container.inventory_mutations.receive(**second_payload, approval_id=approval2,
        idempotency_key="receive-35", ctx=ctx))
    assert stock() == (10, 75, 55, "received")
    assert db.inventory_movements.count_documents({"order_id": order["id"]}) == 2
    assert db.receipts.count_documents({"order_id": order["id"]}) == 2
    current_order = db.orders.find_one({"_id": order["id"]})
    _approve_and_execute(seeded_client, "order_update_status", {
        "order_id": order["id"], "status": "completed", "expected_version": current_order["version"],
    }, "complete-55")
    assert stock() == (10, 75, 55, "completed")
    sync.close()


@pytest.mark.parametrize("fault_point", ["before_receipt_write", "after_inventory_write", "after_movement_write", "before_operation_success"])
def test_receipt_transaction_failure_rolls_back_stock_order_approval_and_receipt(seeded_client, fault_point):
    order = _submit_p001(seeded_client)
    container = seeded_client.app.state.container
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    db = sync[container.settings.mongodb_database]
    _approve_and_execute(seeded_client, "order_update_status", {"order_id": order["id"], "status": "shipped", "expected_version": order["version"]}, "ship-fail")
    payload = {"order_id": order["id"], "receipt_id": "R-FAIL", "warehouse_id": "W01",
               "items": [{"part_id": "P001", "quantity": 20}]}
    ctx = RequestContext("local-owner", "p08-test", run_id="p08-test")
    approval = _run(seeded_client, container.approvals.request_mutation("inventory_receive", payload, ctx, proposal_id="proposal-fail"))["approval_id"]
    _run(seeded_client, container.approvals.resolve_mutation(approval, "approve", "dec-fail", ctx))
    container.inventory_mutations.fault_hook = lambda point: (_ for _ in ()).throw(RuntimeError("injected")) if point == fault_point else None
    try:
        _run(seeded_client, container.inventory_mutations.receive(**payload, approval_id=approval, idempotency_key="fail", ctx=ctx))
        assert False, "failure hook should abort the transaction"
    except RuntimeError as exc:
        assert str(exc) == "injected"
    finally:
        container.inventory_mutations.fault_hook = None
    assert (db.inventories.find_one({"_id": "I001"})["on_hand"], db.inventories.find_one({"_id": "I001"})["inbound"]) == (20, 65)
    assert db.orders.find_one({"_id": order["id"]})["items"][0]["received_qty"] == 0
    assert db.receipts.count_documents({"receipt_id": "R-FAIL"}) == 0
    assert db.inventory_movements.count_documents({"receipt_id": "R-FAIL"}) == 0
    assert db.approvals.find_one({"_id": approval})["status"] == "pending"
    sync.close()


def test_concurrent_duplicate_receipt_commits_stock_and_movement_once(seeded_client):
    order = _submit_p001(seeded_client)
    container = seeded_client.app.state.container
    _approve_and_execute(seeded_client, "order_update_status", {
        "order_id": order["id"], "status": "shipped", "expected_version": order["version"],
    }, "ship-concurrent")
    payload = {"order_id": order["id"], "receipt_id": "R-CONCURRENT", "warehouse_id": "W01",
               "items": [{"part_id": "P001", "quantity": 20}]}
    ctx = RequestContext("local-owner", "p08-concurrent", run_id="p08-concurrent")
    container = seeded_client.app.state.container
    approval = _run(seeded_client, container.approvals.request_mutation(
        "inventory_receive", payload, ctx, proposal_id="proposal-concurrent"))["approval_id"]
    _run(seeded_client, container.approvals.resolve_mutation(approval, "approve", "decision-concurrent", ctx))

    async def submit_twice():
        async def submit():
            try:
                return await container.inventory_mutations.receive(
                    **payload, approval_id=approval, idempotency_key="receive-concurrent", ctx=ctx)
            except Exception as exc:
                return exc
        return await asyncio.gather(submit(), submit())

    results = _run(seeded_client, submit_twice())
    successes = [result for result in results if isinstance(result, dict)]
    assert len(successes) == 1
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        db = sync[container.settings.mongodb_database]
        inventory = db.inventories.find_one({"_id": "I001"})
        persisted_order = db.orders.find_one({"_id": order["id"]})
        assert (inventory["inbound"], inventory["on_hand"], persisted_order["items"][0]["received_qty"]) == (45, 40, 20)
        assert db.receipts.count_documents({"receipt_id": "R-CONCURRENT"}) == 1
        assert db.inventory_movements.count_documents({"receipt_id": "R-CONCURRENT"}) == 1
    finally:
        sync.close()
