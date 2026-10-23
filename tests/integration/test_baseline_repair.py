"""P01-F02：旧基线修正默认 dry-run、显式 apply 并拒绝业务变化。"""

from __future__ import annotations

from backend.app.repositories.mongo import MongoResources
from backend.app.services.baseline_repair import OLD_BASELINE, repair_p01_baseline
from backend.app.services.seeding import seed
from tests.integration.conftest import make_settings


async def _set_old(db, inventory_id: str, **overrides):
    values = dict(OLD_BASELINE[inventory_id])
    values.update(overrides)
    await db["inventories"].update_one({"_id": inventory_id}, {"$set": values})


async def test_repair_dry_run_then_apply_increments_versions(db_name, mongo_admin):
    settings = make_settings(db_name)
    mongo = await MongoResources.open(settings)
    try:
        await seed(mongo.db, reset=True)
        for inventory_id in OLD_BASELINE:
            await _set_old(mongo.db, inventory_id)

        preview = await repair_p01_baseline(mongo, apply=False)
        assert preview.conflicts == []
        assert len(preview.changes) == 3
        assert preview.applied is False
        assert (await mongo.db["inventories"].find_one({"_id": "I006"}))["on_hand"] == 8

        applied = await repair_p01_baseline(mongo, apply=True)
        assert applied.conflicts == []
        assert applied.applied is True
        i004 = await mongo.db["inventories"].find_one({"_id": "I004"})
        i006 = await mongo.db["inventories"].find_one({"_id": "I006"})
        i007 = await mongo.db["inventories"].find_one({"_id": "I007"})
        assert (i004["on_hand"], i004["inbound"], i004["version"]) == (15, 0, 2)
        assert (i006["on_hand"], i006["inbound"], i006["version"]) == (12, 0, 2)
        assert (i007["on_hand"], i007["inbound"], i007["version"]) == (5, 0, 2)
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)


async def test_repair_refuses_modified_inventory(db_name, mongo_admin):
    settings = make_settings(db_name)
    mongo = await MongoResources.open(settings)
    try:
        await seed(mongo.db, reset=True)
        await _set_old(mongo.db, "I006", on_hand=9)

        report = await repair_p01_baseline(mongo, apply=True)
        assert report.applied is False
        assert report.conflicts
        assert "I006" in report.conflicts[0]
        assert (await mongo.db["inventories"].find_one({"_id": "I006"}))["on_hand"] == 9
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)


async def test_repair_refuses_related_new_order(db_name, mongo_admin):
    settings = make_settings(db_name)
    mongo = await MongoResources.open(settings)
    try:
        await seed(mongo.db, reset=True)
        await _set_old(mongo.db, "I004")
        await mongo.db["orders"].insert_one(
            {
                "_id": "O-NEW",
                "number": "PO-NEW-001",
                "owner_id": "local-owner",
                "draft_id": "D-NEW",
                "supplier_id": "S02",
                "warehouse_id": "W02",
                "items": [
                    {
                        "part_id": "P002",
                        "quantity": 1,
                        "unit_price_cents": 800,
                        "quote_id": "Q04",
                        "line_total_cents": 800,
                        "received_qty": 0,
                    }
                ],
                "total_cents": 800,
                "status": "submitted",
                "version": 1,
                "created_at": "2026-10-20T00:00:00Z",
            }
        )

        report = await repair_p01_baseline(mongo, apply=True)
        assert report.applied is False
        assert any("related order O-NEW" in conflict for conflict in report.conflicts)
        assert (await mongo.db["inventories"].find_one({"_id": "I004"}))["inbound"] == 5
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)


async def test_repair_is_noop_on_current_fixture(db_name, mongo_admin):
    settings = make_settings(db_name)
    mongo = await MongoResources.open(settings)
    try:
        await seed(mongo.db, reset=True)
        report = await repair_p01_baseline(mongo, apply=True)
        assert report.conflicts == []
        assert report.changes == []
        assert report.applied is False
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)
