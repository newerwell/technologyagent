from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import shutil
from uuid import uuid4

import pytest
from PIL import Image
from pymongo import MongoClient

from backend.app.contracts.artifacts import CollectedOutput
from backend.app.contracts.common import AppError, RequestContext, SystemClock
from backend.app.repositories.artifacts import ArtifactRepository
from backend.app.services.artifacts import ArtifactService


def ctx(owner="owner-a", run="run-a"):
    return RequestContext(owner_id=owner, request_id="req", run_id=run)


def test_artifact_register_open_is_owner_and_id_bound():
    class MemoryRepository:
        def __init__(self): self.rows = {}
        async def insert(self, document): self.rows[document["_id"]] = document
        async def get(self, artifact_id, owner_id):
            value = self.rows.get(artifact_id)
            return value if value and value["owner_id"] == owner_id else None

    repository = MemoryRepository()
    storage = Path(".runtime") / ("test-artifacts-" + uuid4().hex)
    storage.mkdir(parents=True, exist_ok=False)
    service = ArtifactService(repository, storage, SystemClock())
    output = CollectedOutput(filename="供应商比较.csv", content="供应商,总额(分)\nS01,66000\n".encode("utf-8-sig"),
                             mime="text/csv", kind="csv")
    import asyncio
    try:
        artifact = asyncio.run(service.register(output, ctx()))
        opened, body = asyncio.run(service.open(artifact.id, ctx()))
        assert opened.id == artifact.id and body == output.content
        with pytest.raises(AppError) as cross:
            asyncio.run(service.open(artifact.id, ctx("owner-b")))
        assert cross.value.http_status == 404
        for fake in ("../../secret", str(storage / "secret"), "art_" + "0" * 32):
            with pytest.raises(AppError) as denied:
                asyncio.run(service.open(fake, ctx()))
            assert denied.value.http_status == 404
        with pytest.raises(AppError) as invalid_png:
            asyncio.run(service.register(CollectedOutput(filename="broken.png", content=b"\x89PNG\r\n\x1a\n",
                                                          mime="image/png", kind="png"), ctx()))
        assert invalid_png.value.http_status == 422
        png = BytesIO()
        Image.new("RGB", (2, 2), "white").save(png, format="PNG")
        valid = asyncio.run(service.register(CollectedOutput(filename="chart.png", content=png.getvalue(),
                                                              mime="image/png", kind="png"), ctx()))
        assert asyncio.run(service.open(valid.id, ctx()))[1] == png.getvalue()
    finally:
        shutil.rmtree(storage, ignore_errors=True)


def test_download_endpoint_uses_artifact_id_and_returns_not_found_for_missing_file(seeded_client, mongo_admin):
    settings = seeded_client.app.state.settings
    owner_id = seeded_client.get("/api/session/me").json()["data"]["owner_id"]
    artifact_id = "art_" + uuid4().hex
    run_id = "run_artifact_test"
    storage_key = f"{owner_id}/{run_id}/{artifact_id}.json"
    root = settings.resolved_storage_root
    file_path = root / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(br'{"scope":"\u4ed3\u5e93 W01","total_cents":66000}')
    mongo = MongoClient(settings.mongodb_uri.get_secret_value())
    collection = mongo[settings.mongodb_database]["artifacts"]
    collection.insert_one({
        "_id": artifact_id, "id": artifact_id, "owner_id": owner_id, "run_id": run_id,
        "kind": "json", "mime": "application/json", "filename": "采购报告.json",
        "storage_key": storage_key, "source_refs": [], "created_at": datetime.now(timezone.utc),
        "status": "ready", "size_bytes": file_path.stat().st_size,
    })
    try:
        response = seeded_client.get(f"/api/artifacts/{artifact_id}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.headers["content-disposition"].startswith("attachment;")
        assert response.json()["total_cents"] == 66000
        file_path.unlink()
        assert seeded_client.get(f"/api/artifacts/{artifact_id}").status_code == 404
        assert seeded_client.get("/api/artifacts/../../secret").status_code in {404, 422}
    finally:
        collection.delete_one({"_id": artifact_id})
        file_path.unlink(missing_ok=True)
        mongo.close()


def test_thread_artifact_history_lists_all_runs_without_exposing_storage_key(seeded_client):
    owner_id = seeded_client.get("/api/session/me").json()["data"]["owner_id"]
    settings = seeded_client.app.state.settings
    mongo = MongoClient(settings.mongodb_uri.get_secret_value())
    db = mongo[settings.mongodb_database]
    thread_id = "thr_artifact_history_" + uuid4().hex
    run_ids = ["run_old_" + uuid4().hex, "run_new_" + uuid4().hex]
    artifact_ids = ["art_" + uuid4().hex, "art_" + uuid4().hex]

    db["threads"].insert_one({
        "_id": thread_id, "owner_id": owner_id, "title": "artifact history",
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    })

    for index, run_id in enumerate(run_ids):
        db["runs"].insert_one({
                "_id": run_id, "owner_id": owner_id, "thread_id": thread_id,
                    "request_id": "req-artifact-history-" + uuid4().hex,
                "created_at": datetime.now(timezone.utc),
            })
        db["artifacts"].insert_one({
                "_id": artifact_ids[index], "id": artifact_ids[index], "owner_id": owner_id,
                "run_id": run_id, "kind": "csv", "mime": "text/csv",
                "filename": f"report-{index}.csv", "storage_key": f"private/{run_id}/report.csv",
                "source_refs": [{"entity": "quote", "id": "Q01", "call_id": f"call-{index}"}],
                "created_at": datetime.now(timezone.utc), "status": "ready", "size_bytes": 20,
            })

    try:
        response = seeded_client.get("/api/artifacts", params={"thread_id": thread_id})
        assert response.status_code == 200, response.text
        artifacts = response.json()["data"]
        assert {item["artifact_id"] for item in artifacts} == set(artifact_ids)
        assert {item["run_id"] for item in artifacts} == set(run_ids)
        assert all("storage_key" not in item for item in artifacts)
        assert all(item["download_url"].startswith("/api/artifacts/art_") for item in artifacts)
    finally:
        db["runs"].delete_many({"_id": {"$in": run_ids}, "owner_id": owner_id})
        db["artifacts"].delete_many({"_id": {"$in": artifact_ids}, "owner_id": owner_id})
        db["threads"].delete_one({"_id": thread_id, "owner_id": owner_id})
        mongo.close()
