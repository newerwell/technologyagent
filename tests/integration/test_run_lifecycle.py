"""P02 进程重启孤儿 run 的启动恢复与历史删除。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.app.contracts.common import FixedClock, RequestContext
from backend.app.main import create_app
from backend.app.repositories.indexes import ensure_indexes
from backend.app.repositories.mongo import MongoResources
from backend.app.services.runs import RunService
from tests.integration.conftest import make_settings


async def test_startup_marks_orphan_failed_and_delete_conversation(db_name, mongo_admin):
    settings = make_settings(db_name)
    mongo = await MongoResources.open(settings)
    try:
        await ensure_indexes(mongo.db)
        service = RunService(
            mongo, FixedClock(datetime(2026, 10, 24, 2, 0, 0, tzinfo=timezone.utc))
        )
        run = await service.create(
            None,
            "before restart",
            "restart-request",
            RequestContext(owner_id="local-owner", request_id="restart-request"),
        )
    finally:
        await mongo.close()

    application = create_app(settings)
    with TestClient(
        application,
        base_url=f"http://127.0.0.1:{settings.api_port}",
        client=("127.0.0.1", 50000),
    ) as client:
        session = client.post("/api/session/local")
        assert session.status_code == 200
        detail = client.get(f"/api/runs/{run.id}")
        assert detail.status_code == 200
        data = detail.json()["data"]
        assert data["status"] == "failed"
        assert data["error_code"] == "PROCESS_RESTARTED"
        events = client.get(f"/api/runs/{run.id}/events?after_seq=0").json()["data"]
        assert [event["type"] for event in events] == [
            "error",
            "run_finished",
            "stream_end",
        ]
        assert events[0]["payload"]["code"] == "PROCESS_RESTARTED"

        deleted = client.delete(f"/api/conversations/{run.thread_id}")
        assert deleted.status_code == 200
        assert deleted.json()["data"]["deleted"] is True
        assert client.get(f"/api/conversations/{run.thread_id}").status_code == 404
        assert client.get(f"/api/runs/{run.id}").status_code == 404
    mongo_admin.drop_database(db_name)
