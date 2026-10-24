"""P00-A02：存活/就绪、统一 Envelope 与错误路由。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.main import create_app
from tests.integration.conftest import make_settings


def test_health_ok_and_does_not_leak_config(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"] == {
        "status": "ok",
        "app": "TechnologyAgent",
        "component": "api",
    }
    assert body["error"] is None
    assert body["meta"]["request_id"] == response.headers["x-request-id"]
    serialized = json.dumps(body)
    assert "mongodb://" not in serialized
    assert "API_KEY" not in serialized
    assert "test-only-local-session-secret" not in serialized


def test_unknown_route_returns_envelope_404(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["meta"]["request_id"]


def test_ready_checks_db_primary_and_real_transaction(client):
    response = client.get("/ready")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    checks = body["data"]["checks"]
    assert checks["db"]["status"] == "ok"
    assert checks["transaction"]["status"] == "ok"
    assert checks["model"]["status"] == "fake"
    assert checks["mcp"]["status"] in {"ok", "unavailable"}
    assert checks["sandbox"]["status"] == "disabled"


def test_health_still_ok_but_ready_503_when_database_is_down(db_name, mongo_admin):
    settings = make_settings(
        db_name,
        mongodb_uri=SecretStr("mongodb://127.0.0.1:1/?directConnection=true"),
        storage_root=Path("storage") / "test-down",
    )
    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 50000)) as isolated:
        health = isolated.get("/health")
        assert health.status_code == 200
        ready = isolated.get("/ready")
        assert ready.status_code == 503
        body = ready.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
        assert body["error"]["retryable"] is True
        assert body["data"]["checks"]["db"]["status"] == "unavailable"
        assert body["data"]["checks"]["transaction"]["status"] == "unavailable"
        assert "mongodb://" not in json.dumps(body)
    mongo_admin.drop_database(db_name)
