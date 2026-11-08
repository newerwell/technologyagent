"""R5 API and MCP remote reads use the same real HTTP simulator contract."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import ClassVar
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

import mcp_server.server as mcp_server
from backend.app.main import create_app
from tests.integration.conftest import make_settings


class _Simulator(BaseHTTPRequestHandler):
    requests: ClassVar[list[tuple[str, int]]] = []
    omit_status = False

    def do_GET(self):
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        page = int(query.get("page", ["1"])[0])
        page_size = int(query.get("page_size", ["1"])[0])
        type(self).requests.append((parsed.path, page))
        if parsed.path == "/inventory_page":
            records = [{"id": "I01", "part_id": "P01", "warehouse_id": "W01", "on_hand": 20,
                        "reserved": 5, "inbound": 10, "safety_stock": 30, "target_stock": 80,
                        "version": 1, "unit": "套"}]
        else:
            records = [
                {"id": "S01", "code": "S01", "name": "供应商一", "status": "active"},
                {"id": "S02", "code": "S02", "name": "供应商二", "status": "inactive"},
            ]
            if type(self).omit_status:
                records[0].pop("status")
        total = len(records)
        pages = (total + page_size - 1) // page_size
        payload = {"records": records[(page - 1) * page_size:page * page_size],
                   "total": total, "page": page, "page_size": page_size, "pages": pages}
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *_args):
        pass


def _simulator():
    _Simulator.requests = []
    _Simulator.omit_status = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Simulator)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_api_and_mcp_remote_reads_share_complete_mapped_result(db_name, mongo_admin, monkeypatch):
    server, thread = _simulator()
    url = f"http://127.0.0.1:{server.server_port}"
    settings = make_settings(db_name, erp_base_url=url, suppliers_data_source="remote_erp")
    app = create_app(settings)
    try:
        with TestClient(app, base_url=f"http://127.0.0.1:{settings.api_port}",
                        client=("127.0.0.1", 50000)) as client:
            assert client.post("/api/session/local").status_code == 200
            response = client.get("/api/suppliers", params={"page": 2, "page_size": 1})
            assert response.status_code == 200, response.text
            api_result = response.json()
            assert api_result["meta"]["data_source"] == "remote_erp"
            assert api_result["data"]["records"][0]["id"] == "S02"
            container = app.state.container
            runtime = SimpleNamespace(business_providers=container.business_providers,
                                      provider_queries=container.provider_queries,
                                      inventory=SimpleNamespace(inventory=container.inventory))
            monkeypatch.setattr(mcp_server, "_runtime", runtime)
            ctx = SimpleNamespace(owner_id="local-owner", request_id="mcp:test", run_id="test",
                                  actor="main", call_id="call-test")
            # Exercise the exact shared dispatcher used by the registered MCP tools.
            mcp_result = asyncio.run(mcp_server._business_call("supplier_page", {"page": 2, "page_size": 1}, ctx))
            assert mcp_result["ok"] is True
            assert mcp_result["data"] == api_result["data"]
            assert mcp_result["meta"]["data_source"] == "remote_erp"
            assert _Simulator.requests == [
                ("/supplier_page", 1), ("/supplier_page", 2),
                ("/supplier_page", 1), ("/supplier_page", 2),
            ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        mongo_admin.drop_database(db_name)


def test_api_rejects_incomplete_remote_entity_without_mongo_fallback(db_name, mongo_admin):
    server, thread = _simulator()
    _Simulator.omit_status = True
    settings = make_settings(db_name, erp_base_url=f"http://127.0.0.1:{server.server_port}",
                             suppliers_data_source="remote_erp")
    app = create_app(settings)
    try:
        with TestClient(app, base_url=f"http://127.0.0.1:{settings.api_port}",
                        client=("127.0.0.1", 50000)) as client:
            assert client.post("/api/session/local").status_code == 200
            response = client.get("/api/suppliers", params={"page_size": 1})
            assert response.status_code == 502
            assert response.json()["error"]["code"] == "REMOTE_DATA_INVALID"
            assert "status" in response.json()["error"]["message"]
            assert response.json()["meta"]["data_source"] == "none"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        mongo_admin.drop_database(db_name)


def test_remote_inventory_summary_aggregates_validated_provider_records(db_name, mongo_admin):
    server, thread = _simulator()
    settings = make_settings(db_name, erp_base_url=f"http://127.0.0.1:{server.server_port}",
                             inventory_data_source="remote_erp")
    app = create_app(settings)
    try:
        with TestClient(app, base_url=f"http://127.0.0.1:{settings.api_port}",
                        client=("127.0.0.1", 50000)) as client:
            assert client.post("/api/session/local").status_code == 200
            response = client.get("/api/inventory/summary", params={"warehouse_id": "W01"})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["meta"]["data_source"] == "remote_erp"
            assert result["data"]["records"] == 1
            assert result["data"]["total_inbound"] == 10
            assert result["data"]["total_shortage"] == 55
            assert _Simulator.requests == [("/inventory_page", 1)]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        mongo_admin.drop_database(db_name)
