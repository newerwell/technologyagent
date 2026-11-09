"""Real Mongo transactions with fixed business time and a later operational clock."""

from datetime import datetime, timezone

import pytest

from backend.app.contracts.common import FixedClock, RequestContext
from backend.app.contracts.order_workflow import DraftPatch, DraftPrepareRequest, ResumeRequest
from backend.app.integrations.local_provider import LocalProvider
from backend.app.repositories.catalog import CatalogRepository
from backend.app.repositories.indexes import ensure_indexes
from backend.app.repositories.inventory import InventoryRepository
from backend.app.repositories.mongo import MongoResources
from backend.app.repositories.orders import OrderRepository
from backend.app.services.approvals import ApprovalService
from backend.app.services.business_mutations import BusinessMutationService
from backend.app.services.drafts import DraftService
from backend.app.services.mutations import MutationService
from backend.app.services.replenishment import ReplenishmentService
from backend.app.services.seeding import FIXED_NOW, seed
from tests.integration.conftest import make_settings


@pytest.mark.asyncio
async def test_fixed_fixture_clock_preserves_edit_approval_replay_and_amendment_timestamps(db_name, mongo_admin):
    settings = make_settings(db_name)
    mongo = await MongoResources.open(settings)
    wall_now = datetime(2035, 1, 1, tzinfo=timezone.utc)
    wall, business = FixedClock(wall_now), FixedClock(FIXED_NOW)
    ctx = RequestContext(owner_id="local-owner", request_id="fixture-clock", run_id="fixture-clock-run")
    try:
        await ensure_indexes(mongo.db)
        await seed(mongo.db, reset=True)
        await mongo.db.runs.insert_one({"_id": ctx.run_id, "owner_id": ctx.owner_id,
            "thread_id": "fixture-clock-thread", "status": "running", "cancel_requested": False, "commit_fence": 0})
        catalog = CatalogRepository(mongo)
        inventory = InventoryRepository(mongo)
        orders = OrderRepository(mongo)
        replenishment = ReplenishmentService(catalog, inventory, business)
        drafts = DraftService(mongo, catalog, replenishment, wall, business_clock=business)
        approvals = ApprovalService(mongo, wall)
        mutations = MutationService(mongo, wall, inventory, orders, business_clock=business)
        provider = LocalProvider({"mutations": mutations})
        mutations.set_providers({name: provider for name in ("inventory", "parts", "suppliers", "orders")})
        prepared = await drafts.prepare(DraftPrepareRequest(part_ids=["P001"], warehouse_id="W01", max_lead_days=7), ctx)
        draft = prepared["drafts"][0]
        assert (draft["items"][0]["quantity"], draft["total_cents"]) == (55, 66000)
        patch = DraftPatch(expected_version=1, items=[{"part_id": "P001", "quote_id": "Q01", "quantity": 60}])
        await drafts.validate_patch(draft["id"], patch, ctx)
        edited = await drafts.patch(draft["id"], patch, ctx)
        assert (edited["version"], edited["total_cents"]) == (2, 72000)
        approval = await approvals.request(draft["id"], ctx.run_id, ctx)
        await approvals.resolve(approval["approval_id"], ResumeRequest(
            interrupt_id="fixture-clock-interrupt", decision="approve", expected_version=2,
            idempotency_key="fixture-clock-decision"), ctx)
        result = await mutations.execute(draft["id"], approval["approval_id"], "fixture-clock-create", ctx)
        replay = await mutations.execute(draft["id"], approval["approval_id"], "fixture-clock-create", ctx)
        assert replay == result
        order_id = result["order"]["id"]
        operation = await mongo.db.operations.find_one({"_id": result["operation_id"]})
        order = await mongo.db.orders.find_one({"_id": order_id})
        assert order["created_at"] == wall_now
        assert operation["created_at"] == wall_now
        assert operation["lease_expires_at"] > wall_now
        amendment = {"order_id": order_id, "expected_version": 1,
                     "items": [{"part_id": "P001", "quote_id": "Q01", "quantity": 61}]}
        proposal = await approvals.request_mutation("order_update", amendment, ctx)
        await approvals.resolve_mutation(proposal["approval_id"], "approve", "fixture-clock-amend-decision",
                                         ctx, expected_version=1)
        generic = BusinessMutationService(mongo, wall, business_clock=business)
        await generic.execute(proposal["approval_id"], "fixture-clock-amend", ctx, expected_action="order_update")
        order = await mongo.db.orders.find_one({"_id": order_id})
        stock = await mongo.db.inventories.find_one({"_id": "I001"})
        assert (order["total_cents"], stock["inbound"], stock["on_hand"]) == (73200, 71, 20)
        assert await mongo.db.orders.count_documents({}) == 3
        assert await mongo.db.operations.count_documents({"status": "succeeded"}) == 2
    finally:
        await mongo.close()
        mongo_admin.drop_database(db_name)
