"""P00 集成测试夹具：真实 Mongo replica set + FastAPI TestClient。"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pydantic import SecretStr

from backend.app.config import DEFAULT_MONGODB_URI, Settings
from backend.app.main import create_app

TEST_MONGODB_URI = os.environ.get("MONGODB_TEST_URI", DEFAULT_MONGODB_URI)
TEST_DB_PREFIX = "technologyagent_test_"


def assert_test_db(name: str) -> None:
    if not name.startswith(TEST_DB_PREFIX):
        raise AssertionError(f"refusing to touch database without {TEST_DB_PREFIX!r}: {name}")


def make_settings(database: str, **overrides: object) -> Settings:
    assert_test_db(database)
    values: dict[str, object] = {
        "app_mode": "local",
        "mongodb_uri": SecretStr(TEST_MONGODB_URI),
        "mongodb_database": database,
        "model_mode": "fake",
        "model_name": "",
        "model_api_key": None,
        "local_session_secret": SecretStr("test-only-local-session-secret"),
        "storage_root": Path("storage"),
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture()
def db_name() -> str:
    return f"{TEST_DB_PREFIX}{uuid.uuid4().hex[:12]}"


@pytest.fixture()
def mongo_admin():
    client = MongoClient(TEST_MONGODB_URI, serverSelectionTimeoutMS=2500)
    try:
        client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            "MongoDB replica set is required for P00 integration tests. "
            "Start it with: docker compose up -d mongodb "
            f"({type(exc).__name__}: {exc})"
        )
    yield client
    client.close()


@pytest.fixture()
def app(db_name: str, mongo_admin):
    settings = make_settings(db_name, storage_root=Path("storage") / "test")
    application = create_app(settings)
    yield application
    assert_test_db(db_name)
    mongo_admin.drop_database(db_name)


@pytest.fixture()
def client(app):
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client
