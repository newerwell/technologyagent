"""P01-T01：seed 幂等、manifest 与历史数据保护。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.repositories.mongo import MongoResources
from backend.app.services.seeding import (
    SeedError,
    build_manifest,
    load_bundle,
    load_manifest,
    seed,
)
from tests.integration.conftest import make_settings


async def test_seed_is_idempotent_and_preserves_user_orders(db_name, mongo_admin):
    settings = make_settings(db_name)
    mongo = await MongoResources.open(settings)
    try:
        first = await seed(mongo.db, reset=True)
        second = await seed(mongo.db)
        assert first.counts == second.counts
        assert first.canonical_hash == second.canonical_hash
        assert await mongo.db["parts"].count_documents({}) == 6
        assert await mongo.db["suppliers"].count_documents({}) == 3
        assert await mongo.db["quotes"].count_documents({}) == 8
        assert await mongo.db["inventories"].count_documents({}) == 8
        assert await mongo.db["drafts"].count_documents({}) == 2
        assert await mongo.db["orders"].count_documents({}) == 2

        custom = {
            "_id": "O-CUSTOM",
            "number": "PO-CUSTOM-001",
            "owner_id": "local-owner",
            "draft_id": "D-CUSTOM",
            "supplier_id": "S01",
            "warehouse_id": "W01",
            "items": [],
            "total_cents": 0,
            "status": "draft",
            "version": 1,
            "created_at": "2026-10-20T00:00:00Z",
        }
        await mongo.db["orders"].insert_one(custom)
        await seed(mongo.db)
        assert await mongo.db["orders"].count_documents({}) == 3
        assert await mongo.db["orders"].find_one({"_id": "O-CUSTOM"}) is not None
        assert await mongo.db["orders"].find_one({"_id": "O001"}) is not None
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)


async def test_seed_manifest_matches_fixture_content():
    bundle = load_bundle()
    manifest = load_manifest()
    assert build_manifest(bundle) == manifest
    assert manifest["counts"] == {
        "parts": 6,
        "suppliers": 3,
        "quotes": 8,
        "inventories": 8,
        "drafts": 2,
        "orders": 2,
        "warehouses": 2,
    }
    assert manifest["total_summary"]["records"] == 8
    assert manifest["total_summary"]["warning_count"] == 4


async def test_reset_is_rejected_for_non_test_database():
    fake = SimpleNamespace(name="technologyagent_dev")
    with pytest.raises(SeedError, match="--reset"):
        await seed(fake, reset=True)
