"""P00-T04：本地会话身份、Cookie、过期与配置脱敏。"""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.api.dependencies import get_context
from backend.app.config import Settings, load_settings
from backend.app.contracts.common import RequestContext
from backend.app.main import create_app
from tests.integration.conftest import make_settings


def test_body_owner_id_is_ignored(client):
    response = client.post("/api/session/local", json={"owner_id": "attacker"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"]["owner_id"] == "local-owner"
    assert body["meta"]["scope"] == "local-owner"

    me = client.get("/api/session/me")
    assert me.status_code == 200
    assert me.json()["data"]["owner_id"] == "local-owner"


def test_cookie_attributes_and_only_digest_is_stored(client, db_name, mongo_admin):
    response = client.post("/api/session/local")
    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Path=/" in set_cookie
    assert "Max-Age=86400" in set_cookie

    raw_token = client.cookies.get("ta_local_session")
    assert raw_token
    docs = list(mongo_admin[db_name]["sessions"].find({}))
    assert len(docs) == 1
    digest = hmac.new(
        b"test-only-local-session-secret", raw_token.encode("utf-8"), sha256
    ).hexdigest()
    assert docs[0]["_id"] == digest
    assert raw_token not in docs[0].values()


def test_protected_route_requires_cookie(client):
    response = client.get("/api/session/me")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"
    assert body["ok"] is False


def test_invalid_cookie_is_rejected(client):
    client.cookies.set("ta_local_session", "not-a-real-token")
    response = client.get("/api/session/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_non_local_mode_cannot_create_development_session(db_name, mongo_admin):
    settings = make_settings(
        db_name, app_mode="prod", storage_root=Path("storage") / "test-prod"
    )
    with TestClient(
        create_app(settings),
        base_url=f"http://127.0.0.1:{settings.api_port}",
        client=("127.0.0.1", 50000),
    ) as prod_client:
        response = prod_client.post("/api/session/local")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "LOCAL_SESSION_DISABLED"
    mongo_admin.drop_database(db_name)


def test_non_loopback_peer_is_rejected_even_with_spoofed_forwarded_header(app):
    # 默认 TestClient peer 是 testclient，不是回环；伪造 X-Forwarded-For 不能提权。
    settings = app.state.settings
    with TestClient(
        app,
        base_url=f"http://127.0.0.1:{settings.api_port}",
        headers={"X-Forwarded-For": "127.0.0.1"},
    ) as remote_client:
        response = remote_client.post("/api/session/local")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "LOCAL_SESSION_DISABLED"


def test_allowed_frontend_origin_and_proxy_host_are_accepted(client):
    response = client.post(
        "/api/session/local",
        headers={
            "Host": "127.0.0.1:3030",
            "Origin": "http://127.0.0.1:3030",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["owner_id"] == "local-owner"


def test_cross_origin_session_request_is_rejected(client):
    response = client.post(
        "/api/session/local",
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "LOCAL_SESSION_DISABLED"


def test_unexpected_host_is_rejected(client):
    response = client.post(
        "/api/session/local",
        headers={"Host": "192.0.2.10:8030"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "LOCAL_SESSION_DISABLED"


def test_backend_origin_is_not_a_browser_frontend_origin(client):
    response = client.post(
        "/api/session/local",
        headers={"Origin": "http://127.0.0.1:8030"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "LOCAL_SESSION_DISABLED"


def test_test_identity_b_uses_dependency_override_only(app, client):
    app.dependency_overrides[get_context] = lambda: RequestContext(
        owner_id="owner-b", request_id="test-request"
    )
    response = client.get("/api/session/me")
    assert response.status_code == 200
    assert response.json()["data"]["owner_id"] == "owner-b"


def test_expired_session_is_rejected(client, db_name, mongo_admin):
    created = client.post("/api/session/local")
    assert created.status_code == 200
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    mongo_admin[db_name]["sessions"].update_many({}, {"$set": {"expires_at": past}})
    response = client.get("/api/session/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_session_creation_returns_503_when_database_is_down(db_name, mongo_admin):
    settings = make_settings(
        db_name,
        mongodb_uri=SecretStr("mongodb://127.0.0.1:1/?directConnection=true"),
        storage_root=Path("storage") / "test-session-down",
    )
    with TestClient(
        create_app(settings),
        base_url=f"http://127.0.0.1:{settings.api_port}",
        client=("127.0.0.1", 50000),
    ) as isolated:
        response = isolated.post("/api/session/local")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
        assert response.json()["error"]["retryable"] is True
    mongo_admin.drop_database(db_name)


def test_settings_repr_and_safe_summary_mask_secrets():
    settings = Settings(
        mongodb_uri=SecretStr("mongodb://user:supersecret@127.0.0.1:27027/db"),
        model_api_key=SecretStr("sk-live-secret-value"),
        local_session_secret=SecretStr("local-secret-value"),
        storage_root=Path("storage") / "test-settings",
    )
    rendered = f"{settings!r} {settings.model_dump_json()} {settings.safe_summary()}"
    assert "supersecret" not in rendered
    assert "sk-live-secret-value" not in rendered
    assert "local-secret-value" not in rendered
    assert settings.safe_summary()["model_configured"] is False


def test_load_settings_marks_live_model_unconfigured_without_key():
    settings = load_settings(
        {
            "APP_MODE": "local",
            "MODEL_MODE": "live",
            "MODEL_NAME": "some-model",
            "MODEL_API_KEY": "",
        }
    )
    assert settings.model_mode == "live"
    assert settings.model_api_key is None
    assert settings.model_configured is False
