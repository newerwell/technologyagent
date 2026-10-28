import asyncio
import json

from fastapi.testclient import TestClient

from backend.app.contracts.common import RequestContext
from backend.app.main import create_app
from tests.integration.conftest import make_settings


def test_copied_snapshot_is_shared_by_http_mcp_and_offline_tools(tmp_path, db_name, mongo_admin, monkeypatch):
    path = tmp_path / "inventory_snapshot.json"
    path.write_text(json.dumps({"code": 200, "timestamp": 1792744281356, "data": {
        "total": 0, "pages": 0, "records": [{"id": 72, "partId": 72, "currentQuantity": 100,
            "safetyStock": 10, "warehouseLocation": "A区-1号库", "deleted": 0,
            "partDetail": {"id": 72, "partCode": "M6X20", "name": "螺丝", "unit": "个"}}]}},
        ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()
    settings = make_settings(db_name, inventory_snapshot_path=path,
        inventory_data_source="local_snapshot", parts_data_source="local_snapshot")
    try:
        app = create_app(settings)
        with TestClient(app, base_url="http://127.0.0.1:8030", client=("127.0.0.1", 50000)) as api:
            assert api.post("/api/session/local").status_code == 200
            response = api.get("/api/inventory?page_size=10")
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["data"]["total"] == 1
            assert body["data"]["records"][0]["on_hand"] == 100
            assert body["data"]["records"][0]["target_stock"] is None
            assert body["meta"]["data_source"] == "local_snapshot"
            assert body["meta"]["reported_source_total"] == 0
            assert body["meta"]["completeness"] == "unknown"
            assert api.get("/api/parts").json()["data"]["records"][0]["name"] == "螺丝"
            assert api.get("/api/inventory/warnings").json()["data"]["total"] == 0
            assert api.get("/api/inventory/summary").json()["data"]["total_shortage"] is None
            assert api.get("/api/quotes").status_code == 409
            assert not app.state.container.business_providers["inventory"].capabilities.write
            assert mongo_admin[db_name].inventories.count_documents({}) == 0

        import mcp_server.server as server
        from backend.app.agent.budget import RunBudget
        from backend.app.agent.local_tools import LocalToolRegistry
        runtime = server.McpRuntime(settings)
        monkeypatch.setattr(server, "_runtime", runtime)
        ctx = RequestContext(owner_id="local-owner", request_id="snapshot-test", run_id="run-test", call_id="call-test")

        async def check_tools():
            for name in ("inventory_page", "inventory_warning"):
                payload = await server._business_call(name, {"page": 1, "page_size": 10}, ctx)
                assert payload["ok"] and payload["meta"]["data_source"] == "local_snapshot"
                assert payload["meta"]["snapshot_id"]
                assert payload["data"]["total"] == (1 if name == "inventory_page" else 0)
                assert payload["data"]["source_refs"]
            registry = LocalToolRegistry(runtime.catalog.catalog._repository, None, runtime.clock,
                inventory_service=runtime.inventory.inventory, replenishment_service=runtime.inventory.replenishment)
            result = await registry.invoke("inventory_page", {}, ctx, RunBudget("run-test"))
            assert result.ok and result.data["total"] == 1
            assert result.meta["data_source"] == "local_snapshot"
            result = await registry.invoke("replenishment_preview", {"part_ids": ["72"], "warehouse_id": "A区-1号库"}, ctx, RunBudget("run-test"))
            assert not result.ok and result.error["code"] == "UNSUPPORTED_OPERATION"

        asyncio.run(check_tools())
        assert path.read_bytes() == before
    finally:
        mongo_admin.drop_database(db_name)
