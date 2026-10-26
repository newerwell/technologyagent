"""Provider selection must govern the real HTTP and order-mutation paths."""

import asyncio

from fastapi.testclient import TestClient
from pymongo import MongoClient

from backend.app.main import create_app
from tests.integration.conftest import _seed_database, make_settings


def _api(settings):
    app = create_app(settings)
    client = TestClient(app, base_url=f"http://127.0.0.1:{settings.api_port}",
                        client=("127.0.0.1", 50000))
    return app, client


def test_remote_modules_without_erp_never_serve_seed_facts(db_name, mongo_admin):
    settings = make_settings(db_name, suppliers_data_source="remote_erp", parts_data_source="remote_erp",
                             inventory_data_source="remote_erp", orders_data_source="remote_erp")
    asyncio.run(_seed_database(settings))
    app, client = _api(settings)
    try:
        with client:
            assert client.post("/api/session/local").status_code == 200
            responses = [client.get("/api/suppliers"), client.get("/api/parts"),
                         client.get("/api/inventory"), client.get("/api/orders")]
            assert [response.status_code for response in responses] == [503, 503, 503, 503]
            assert all(response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE" for response in responses)
            assert all(response.json()["meta"]["data_source"] != "local_seed" for response in responses)
    finally:
        mongo_admin.drop_database(db_name)


def test_snapshot_provider_rejects_approved_order_create_before_local_write(db_name, mongo_admin):
    local = make_settings(db_name)
    asyncio.run(_seed_database(local))
    app, client = _api(local)
    try:
        with client:
            assert client.post("/api/session/local").status_code == 200
            draft = client.post("/api/drafts", json={"part_ids": ["P001"], "warehouse_id": "W01",
                                                     "max_lead_days": 7}).json()["data"]["drafts"][0]
            approval = client.post(f"/api/drafts/{draft['id']}/approval", json={"run_id": "provider-switch"})
            approval_id = approval.json()["data"]["approval_id"]
            assert client.post(f"/api/approvals/{approval_id}/resolve", json={"interrupt_id": "i",
                "decision": "approve", "expected_version": 1, "idempotency_key": "provider-approve"}).status_code == 200

        snapshot = make_settings(db_name, orders_data_source="local_snapshot")
        app2, client2 = _api(snapshot)
        with client2:
            assert client2.post("/api/session/local").status_code == 200
            response = client2.post("/api/orders/create", json={"draft_id": draft["id"],
                "approval_id": approval_id, "idempotency_key": "snapshot-order-create"})
            assert response.status_code == 405
            assert response.json()["error"]["code"] == "UNSUPPORTED_OPERATION"

        mongo = MongoClient(local.mongodb_uri.get_secret_value())
        try:
            db = mongo[db_name]
            assert db.orders.count_documents({}) == 2
            assert db.inventories.find_one({"_id": "I001"})["inbound"] == 10
            assert db.operations.count_documents({"action": "order_create", "status": "succeeded"}) == 0
        finally:
            mongo.close()
    finally:
        mongo_admin.drop_database(db_name)
