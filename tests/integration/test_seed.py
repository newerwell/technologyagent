"""P01-T01：seed 幂等、manifest 与历史数据保护。"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.app.repositories.mongo import MongoResources
from backend.app.services.seeding import (
    SeedError,
    build_manifest,
    load_bundle,
    load_manifest,
    expected_inbound_by_scope,
    seed,
    validate_bundle,
)
from tests.integration.conftest import make_settings


async def test_seed_is_idempotent_and_preserves_user_orders(db_name, mongo_admin):
    settings = make_settings(db_name)
    mongo = await MongoResources.open(settings)
    try:
        first = await seed(mongo.db, reset=True)
        second = await seed(mongo.db)
        assert first.fixture_counts == second.fixture_counts
        assert first.database_counts == second.database_counts
        assert first.fixture_counts["orders"] == 2
        assert first.database_counts["orders"] == 2
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
    assert manifest["total_summary"]["warning_count"] == 2


async def test_reset_is_rejected_for_non_test_database():
    fake = SimpleNamespace(name="technologyagent_dev")
    with pytest.raises(SeedError, match="--reset"):
        await seed(fake, reset=True)

async def test_default_seed_preserves_modified_records_versions_and_valid_new_order(
    db_name, mongo_admin
):
    settings = make_settings(db_name)
    mongo = await MongoResources.open(settings)
    try:
        await seed(mongo.db, reset=True)
        await mongo.db["inventories"].update_one(
            {"_id": "I001"}, {"$set": {"inbound": 65, "version": 2}}
        )
        await mongo.db["orders"].update_one(
            {"_id": "O001"}, {"$set": {"status": "shipped", "version": 2}}
        )

        from datetime import datetime, timezone

        from backend.app.contracts.domain import (
            OrderDraft,
            OrderItem,
            PurchaseOrder,
            PurchaseOrderItem,
        )

        created_at = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
        draft = OrderDraft(
            id="D-REVIEW",
            owner_id="local-owner",
            supplier_id="S01",
            warehouse_id="W01",
            items=[
                OrderItem(
                    part_id="P001",
                    quantity=55,
                    unit_price_cents=1200,
                    quote_id="Q01",
                    line_total_cents=66000,
                )
            ],
            total_cents=66000,
            version=1,
            state="approved",
            source_refs=[],
        )
        order = PurchaseOrder(
            id="O-REVIEW",
            number="PO-REVIEW-001",
            owner_id="local-owner",
            draft_id="D-REVIEW",
            supplier_id="S01",
            warehouse_id="W01",
            items=[
                PurchaseOrderItem(
                    part_id="P001",
                    quantity=55,
                    unit_price_cents=1200,
                    quote_id="Q01",
                    line_total_cents=66000,
                    received_qty=0,
                )
            ],
            total_cents=66000,
            status="submitted",
            version=1,
            created_at=created_at,
        )
        for collection, model in (("drafts", draft), ("orders", order)):
            document = model.model_dump()
            document["_id"] = document.pop("id")
            await mongo.db[collection].insert_one(document)

        await seed(mongo.db)

        inventory = await mongo.db["inventories"].find_one({"_id": "I001"})
        assert inventory["inbound"] == 65
        assert inventory["version"] == 2
        modified_order = await mongo.db["orders"].find_one({"_id": "O001"})
        assert modified_order["status"] == "shipped"
        assert modified_order["version"] == 2
        assert await mongo.db["orders"].find_one({"_id": "O-REVIEW"}) is not None
        assert await mongo.db["drafts"].find_one({"_id": "D-REVIEW"}) is not None
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)


async def test_default_seed_preserves_other_changed_fields_and_reinserts_missing(
    db_name, mongo_admin
):
    settings = make_settings(db_name)
    mongo = await MongoResources.open(settings)
    try:
        await seed(mongo.db, reset=True)
        await mongo.db["parts"].update_one(
            {"_id": "P001"}, {"$set": {"name": "刹车片-业务修改"}}
        )
        await mongo.db["suppliers"].update_one(
            {"_id": "S01"}, {"$set": {"credit_rating": "C"}}
        )
        await mongo.db["quotes"].update_one(
            {"_id": "Q01"}, {"$set": {"unit_price_cents": 1300}}
        )
        await mongo.db["drafts"].update_one(
            {"_id": "D001"}, {"$set": {"state": "rejected"}}
        )
        await mongo.db["inventories"].delete_one({"_id": "I008"})

        await seed(mongo.db)

        assert (await mongo.db["parts"].find_one({"_id": "P001"}))["name"] == "刹车片-业务修改"
        assert (await mongo.db["suppliers"].find_one({"_id": "S01"}))["credit_rating"] == "C"
        assert (await mongo.db["quotes"].find_one({"_id": "Q01"}))["unit_price_cents"] == 1300
        assert (await mongo.db["drafts"].find_one({"_id": "D001"}))["state"] == "rejected"
        assert await mongo.db["inventories"].find_one({"_id": "I008"}) is not None
        assert await mongo.db["inventories"].count_documents({}) == 8
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)


def test_fixture_inbound_matches_unclosed_orders_independently():
    bundle = load_bundle()
    inventory_keys = {(item.part_id, item.warehouse_id) for item in bundle.inventories}
    expected: dict[tuple[str, str], int] = {key: 0 for key in inventory_keys}
    for order in bundle.orders:
        if order.status in {"completed", "cancelled"}:
            continue
        for item in order.items:
            remaining = item.quantity - item.received_qty
            assert remaining >= 0
            key = (item.part_id, order.warehouse_id)
            assert key in inventory_keys, f"open order item has no inventory: {key}"
            expected[key] = expected.get(key, 0) + remaining
    actual = {
        (item.part_id, item.warehouse_id): item.inbound for item in bundle.inventories
    }
    assert actual == expected


def test_completed_and_cancelled_orders_do_not_create_inbound():
    bundle = load_bundle()
    completed = next(order for order in bundle.orders if order.status == "completed")
    cancelled = completed.model_copy(update={"id": "O-CANCEL", "status": "cancelled"})
    expected = expected_inbound_by_scope([completed, cancelled], bundle.inventories)
    assert expected[(completed.items[0].part_id, completed.warehouse_id)] == 0


def test_validate_bundle_rejects_inventory_inbound_mismatch():
    bundle = load_bundle()
    changed = [
        item.model_copy(update={"inbound": item.inbound + 1}) if item.id == "I001" else item
        for item in bundle.inventories
    ]
    bad = replace(bundle, inventories=changed)
    with pytest.raises(SeedError, match="unclosed orders"):
        validate_bundle(bad)


def test_exact_fixture_warning_set_is_only_i001_i005():
    from backend.app.domain.replenishment import stock_state

    bundle = load_bundle()
    warnings = {
        item.id
        for item in bundle.inventories
        if stock_state(item).warning
    }
    assert warnings == {"I001", "I005"}
