"""P01 旧基线显式修正：默认 dry-run，拒绝覆盖业务修改或相关新增订单。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.repositories.mongo import MongoResources
from backend.app.services.seeding import load_bundle

OLD_BASELINE: dict[str, dict[str, Any]] = {
    "I004": {
        "part_id": "P002",
        "warehouse_id": "W02",
        "on_hand": 10,
        "reserved": 0,
        "inbound": 5,
        "safety_stock": 15,
        "target_stock": 30,
        "version": 1,
        "schema_version": 1,
    },
    "I006": {
        "part_id": "P004",
        "warehouse_id": "W01",
        "on_hand": 8,
        "reserved": 2,
        "inbound": 0,
        "safety_stock": 10,
        "target_stock": 20,
        "version": 1,
        "schema_version": 1,
    },
    "I007": {
        "part_id": "P005",
        "warehouse_id": "W02",
        "on_hand": 0,
        "reserved": 0,
        "inbound": 2,
        "safety_stock": 5,
        "target_stock": 10,
        "version": 1,
        "schema_version": 1,
    },
}

COMPARE_FIELDS = (
    "part_id",
    "warehouse_id",
    "on_hand",
    "reserved",
    "inbound",
    "safety_stock",
    "target_stock",
    "version",
    "schema_version",
)
MUTABLE_FIELDS = ("on_hand", "reserved", "inbound", "safety_stock", "target_stock")


class RepairReport(BaseModel):
    database: str
    apply: bool
    changes: list[dict[str, Any]]
    conflicts: list[str]
    applied: bool


class _RepairConflict(RuntimeError):
    def __init__(self, report: RepairReport) -> None:
        super().__init__("baseline repair conflict")
        self.report = report


def _new_values(bundle) -> dict[str, dict[str, Any]]:
    return {item.id: item.model_dump() for item in bundle.inventories if item.id in OLD_BASELINE}


async def _inspect(
    db: AsyncDatabase,
    *,
    session: AsyncClientSession | None = None,
) -> RepairReport:
    bundle = load_bundle()
    new_by_id = _new_values(bundle)
    kwargs: dict[str, Any] = {"session": session} if session is not None else {}
    changes: list[dict[str, Any]] = []
    conflicts: list[str] = []

    allowed_completed = {
        (order.id, item.part_id, order.warehouse_id)
        for order in bundle.orders
        if order.status in {"completed", "cancelled"}
        for item in order.items
    }

    for inventory_id, old in OLD_BASELINE.items():
        document = await db["inventories"].find_one({"_id": inventory_id}, **kwargs)
        if document is None:
            conflicts.append(f"{inventory_id}: target inventory is missing")
            continue
        new = new_by_id.get(inventory_id)
        if new is None:
            conflicts.append(f"{inventory_id}: fixture no longer defines this inventory")
            continue

        current_new = {key: document.get(key) for key in MUTABLE_FIELDS}
        expected_new = {key: new.get(key) for key in MUTABLE_FIELDS}
        if current_new == expected_new:
            continue

        current_old = {key: document.get(key) for key in COMPARE_FIELDS}
        if current_old != old:
            conflicts.append(
                f"{inventory_id}: current fields/version do not match the old baseline; "
                "refusing to overwrite"
            )
            continue

        orders = db["orders"].find(
            {"items.part_id": old["part_id"], "warehouse_id": old["warehouse_id"]},
            **kwargs,
        )
        async for order in orders:
            if order["_id"] in {"O001", "O002"}:
                if (order["_id"], old["part_id"], old["warehouse_id"]) in allowed_completed:
                    if order.get("status") in {"completed", "cancelled"}:
                        continue
            conflicts.append(
                f"{inventory_id}: related order {order['_id']} exists; refusing baseline overwrite"
            )

        after = {key: new.get(key) for key in MUTABLE_FIELDS}
        after["version"] = old["version"] + 1
        changes.append(
            {
                "_id": inventory_id,
                "before": current_old,
                "after": after,
            }
        )

    return RepairReport(
        database=db.name,
        apply=False,
        changes=changes,
        conflicts=conflicts,
        applied=False,
    )


async def repair_p01_baseline(
    mongo: MongoResources, *, apply: bool = False
) -> RepairReport:
    preview = await _inspect(mongo.db)
    if not apply:
        return preview
    if preview.conflicts:
        return preview.model_copy(update={"apply": True})
    if not preview.changes:
        return preview.model_copy(update={"apply": True})

    try:
        async with mongo.transaction() as session:
            report = await _inspect(mongo.db, session=session)
            if report.conflicts:
                raise _RepairConflict(report.model_copy(update={"apply": True}))
            for change in report.changes:
                old = OLD_BASELINE[change["_id"]]
                result = await mongo.db["inventories"].update_one(
                    {
                        "_id": change["_id"],
                        "version": old["version"],
                        "on_hand": old["on_hand"],
                        "reserved": old["reserved"],
                        "inbound": old["inbound"],
                        "safety_stock": old["safety_stock"],
                        "target_stock": old["target_stock"],
                    },
                    {"$set": change["after"]},
                    session=session,
                )
                if result.matched_count != 1:
                    conflict = report.model_copy(
                        update={
                            "apply": True,
                            "conflicts": report.conflicts
                            + [f"{change['_id']}: document changed during repair"],
                        }
                    )
                    raise _RepairConflict(conflict)
            return report.model_copy(update={"apply": True, "applied": True})
    except _RepairConflict as exc:
        return exc.report
