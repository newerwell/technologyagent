"""P01 合成数据加载、对账校验与只补缺失的 seed。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.config import PROJECT_ROOT
from backend.app.contracts.domain import (
    Inventory,
    OrderDraft,
    Part,
    PurchaseOrder,
    Quote,
    Supplier,
)
from backend.app.domain.replenishment import calculate_replenishment, summarize_inventory
from backend.app.repositories.indexes import (
    DRAFTS,
    INVENTORIES,
    ORDERS,
    PARTS,
    P01_COLLECTIONS,
    QUOTES,
    SUPPLIERS,
    ensure_indexes,
)

FIXED_NOW = datetime(2026, 10, 23, 2, 0, 0, tzinfo=timezone.utc)
DEFAULT_FIXTURE_DIR = PROJECT_ROOT / "fixtures" / "v1"
TEST_DB_PREFIX = "technologyagent_test_"


class SeedError(RuntimeError):
    pass


@dataclass(frozen=True)
class FixtureBundle:
    parts: list[Part]
    suppliers: list[Supplier]
    quotes: list[Quote]
    inventories: list[Inventory]
    drafts: list[OrderDraft]
    orders: list[PurchaseOrder]
    raw: dict[str, Any]


class SeedSummary(BaseModel):
    database: str
    fixture_counts: dict[str, int]
    database_counts: dict[str, int]
    canonical_hash: str
    fixture_version: str
    reset: bool
    collections: list[str]


def _load_json(path: Path) -> Any:
    if not path.is_file():
        raise SeedError(f"fixture file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_bundle(fixture_dir: Path = DEFAULT_FIXTURE_DIR) -> FixtureBundle:
    raw = {
        "parts": _load_json(fixture_dir / "parts.json"),
        "suppliers": _load_json(fixture_dir / "suppliers.json"),
        "quotes": _load_json(fixture_dir / "quotes.json"),
        "inventories": _load_json(fixture_dir / "inventories.json"),
        "drafts": _load_json(fixture_dir / "drafts.json"),
        "orders": _load_json(fixture_dir / "orders.json"),
    }
    try:
        bundle = FixtureBundle(
            parts=TypeAdapter(list[Part]).validate_python(raw["parts"]),
            suppliers=TypeAdapter(list[Supplier]).validate_python(raw["suppliers"]),
            quotes=TypeAdapter(list[Quote]).validate_python(raw["quotes"]),
            inventories=TypeAdapter(list[Inventory]).validate_python(raw["inventories"]),
            drafts=TypeAdapter(list[OrderDraft]).validate_python(raw["drafts"]),
            orders=TypeAdapter(list[PurchaseOrder]).validate_python(raw["orders"]),
            raw=raw,
        )
    except Exception as exc:  # noqa: BLE001
        raise SeedError(f"fixture validation failed: {type(exc).__name__}: {exc}") from exc
    validate_bundle(bundle)
    return bundle


def _unique(items: list[Any], field: str, label: str) -> None:
    values = [getattr(item, field) for item in items]
    if len(values) != len(set(values)):
        raise SeedError(f"{label}.{field} must be unique")


def expected_inbound_by_scope(
    orders: list[PurchaseOrder], inventories: list[Inventory]
) -> dict[tuple[str, str], int]:
    """未关闭订单的剩余未收量按 (part, warehouse) 汇总；完成/取消不计。"""
    inventory_keys = {(item.part_id, item.warehouse_id) for item in inventories}
    expected: dict[tuple[str, str], int] = {key: 0 for key in inventory_keys}
    for order in orders:
        if order.status in {"completed", "cancelled"}:
            continue
        for item in order.items:
            remaining = item.quantity - item.received_qty
            if remaining < 0:
                raise SeedError(f"order {order.id} item {item.part_id} has negative remaining")
            key = (item.part_id, order.warehouse_id)
            if key not in inventory_keys:
                raise SeedError(
                    f"open order {order.id} item {item.part_id} has no inventory row {key}"
                )
            expected[key] += remaining
    return expected


def validate_inventory_reconciliation(bundle: FixtureBundle) -> None:
    expected = expected_inbound_by_scope(bundle.orders, bundle.inventories)
    for inventory in bundle.inventories:
        actual = inventory.inbound
        want = expected[(inventory.part_id, inventory.warehouse_id)]
        if actual != want:
            raise SeedError(
                f"inventory {inventory.id} inbound={actual} but unclosed orders expect {want}"
            )


def validate_bundle(bundle: FixtureBundle) -> None:
    _unique(bundle.parts, "id", "parts")
    _unique(bundle.parts, "code", "parts")
    _unique(bundle.suppliers, "id", "suppliers")
    _unique(bundle.suppliers, "code", "suppliers")
    _unique(bundle.quotes, "id", "quotes")
    _unique(bundle.inventories, "id", "inventories")
    _unique(bundle.drafts, "id", "drafts")
    _unique(bundle.orders, "id", "orders")
    _unique(bundle.orders, "number", "orders")
    _unique(bundle.orders, "draft_id", "orders")
    part_ids = {part.id for part in bundle.parts}
    supplier_ids = {supplier.id for supplier in bundle.suppliers}
    quote_ids = {quote.id for quote in bundle.quotes}
    draft_ids = {draft.id for draft in bundle.drafts}
    part_by_id = {part.id: part for part in bundle.parts}
    supplier_by_id = {supplier.id: supplier for supplier in bundle.suppliers}
    quote_by_id = {quote.id: quote for quote in bundle.quotes}

    for quote in bundle.quotes:
        if quote.part_id not in part_ids:
            raise SeedError(f"quote {quote.id} references unknown part {quote.part_id}")
        if quote.supplier_id not in supplier_ids:
            raise SeedError(f"quote {quote.id} references unknown supplier {quote.supplier_id}")

    inventory_keys: set[tuple[str, str]] = set()
    for inventory in bundle.inventories:
        if inventory.part_id not in part_ids:
            raise SeedError(f"inventory {inventory.id} references unknown part {inventory.part_id}")
        key = (inventory.part_id, inventory.warehouse_id)
        if key in inventory_keys:
            raise SeedError(f"duplicate inventory part+warehouse: {key}")
        inventory_keys.add(key)

    for draft in bundle.drafts:
        if draft.supplier_id not in supplier_ids:
            raise SeedError(f"draft {draft.id} references unknown supplier {draft.supplier_id}")
        for item in draft.items:
            if item.part_id not in part_ids:
                raise SeedError(f"draft {draft.id} references unknown part {item.part_id}")
            quote = quote_by_id.get(item.quote_id)
            if quote is None:
                raise SeedError(f"draft {draft.id} references unknown quote {item.quote_id}")
            if quote.part_id != item.part_id or quote.supplier_id != draft.supplier_id:
                raise SeedError(f"draft {draft.id} quote {quote.id} does not match part/supplier")

    draft_by_id = {draft.id: draft for draft in bundle.drafts}
    for order in bundle.orders:
        if order.draft_id not in draft_ids:
            raise SeedError(f"order {order.id} references unknown draft {order.draft_id}")
        draft = draft_by_id[order.draft_id]
        if order.supplier_id != draft.supplier_id or order.warehouse_id != draft.warehouse_id:
            raise SeedError(f"order {order.id} supplier/warehouse differs from draft")
        for item in order.items:
            if item.part_id not in part_ids:
                raise SeedError(f"order {order.id} references unknown part {item.part_id}")
            quote = quote_by_id.get(item.quote_id)
            if quote is None or quote.part_id != item.part_id:
                raise SeedError(f"order {order.id} quote {item.quote_id} does not match part")

    validate_inventory_reconciliation(bundle)

    inventories = {inventory.id: inventory for inventory in bundle.inventories}
    quotes_by_part: dict[str, list[Quote]] = {}
    for quote in bundle.quotes:
        quotes_by_part.setdefault(quote.part_id, []).append(quote)
    p001 = inventories.get("I001")
    if p001 is None or (p001.part_id, p001.warehouse_id) != ("P001", "W01"):
        raise SeedError("I001 must be P001/W01")
    if (p001.on_hand, p001.reserved, p001.inbound, p001.safety_stock, p001.target_stock) != (
        20,
        5,
        10,
        30,
        80,
    ):
        raise SeedError("P001/W01 stock values must be 20/5/10/30/80")

    p001_price = calculate_replenishment(
        p001, quotes_by_part.get("P001", []), bundle.suppliers, None, FIXED_NOW
    )
    if (
        p001_price.available,
        p001_price.projected,
        p001_price.shortage,
        p001_price.recommended_quote_id,
        p001_price.quantity,
        p001_price.total_cents,
    ) != (15, 25, 55, "Q02", 55, 60500):
        raise SeedError("P001 price-priority case does not match contract")
    p001_lead = calculate_replenishment(
        p001, quotes_by_part.get("P001", []), bundle.suppliers, 7, FIXED_NOW
    )
    if (
        p001_lead.recommended_quote_id,
        p001_lead.quantity,
        p001_lead.total_cents,
    ) != ("Q01", 55, 66000):
        raise SeedError("P001 max_lead_days=7 case does not match contract")

    p002 = inventories.get("I004")
    if p002 is None or (p002.part_id, p002.warehouse_id) != ("P002", "W02"):
        raise SeedError("I004 must be P002/W02")
    p002_line = calculate_replenishment(
        p002, quotes_by_part.get("P002", []), bundle.suppliers, None, FIXED_NOW
    )
    if p002_line.projected != p002.safety_stock or p002_line.warning:
        raise SeedError("P002/W02 must be exactly at threshold and not warn")

    p003 = inventories.get("I005")
    if p003 is None or (p003.part_id, p003.warehouse_id) != ("P003", "W01"):
        raise SeedError("I005 must be P003/W01")
    p003_line = calculate_replenishment(
        p003, quotes_by_part.get("P003", []), bundle.suppliers, None, FIXED_NOW
    )
    if p003_line.actionable or p003_line.missing_fields != ["valid_quote"]:
        raise SeedError("P003/W01 must report missing valid_quote and not be actionable")


def _canonical_payload(bundle: FixtureBundle) -> dict[str, Any]:
    return {
        "parts": [item.model_dump(mode="json") for item in sorted(bundle.parts, key=lambda x: x.id)],
        "suppliers": [
            item.model_dump(mode="json") for item in sorted(bundle.suppliers, key=lambda x: x.id)
        ],
        "quotes": [item.model_dump(mode="json") for item in sorted(bundle.quotes, key=lambda x: x.id)],
        "inventories": [
            item.model_dump(mode="json") for item in sorted(bundle.inventories, key=lambda x: x.id)
        ],
        "drafts": [item.model_dump(mode="json") for item in sorted(bundle.drafts, key=lambda x: x.id)],
        "orders": [item.model_dump(mode="json") for item in sorted(bundle.orders, key=lambda x: x.id)],
    }


def canonical_hash(bundle: FixtureBundle) -> str:
    payload = json.dumps(
        _canonical_payload(bundle),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _summary_for(inventories: list[Inventory], warehouse_id: str | None):
    return summarize_inventory(inventories, warehouse_id)


def build_manifest(bundle: FixtureBundle, fixture_version: str = "v1") -> dict[str, Any]:
    warehouses = sorted({inventory.warehouse_id for inventory in bundle.inventories})
    warehouse_summary = {
        warehouse: _summary_for(
            [inventory for inventory in bundle.inventories if inventory.warehouse_id == warehouse],
            warehouse,
        ).model_dump(mode="json")
        for warehouse in warehouses
    }
    counts = {
        "parts": len(bundle.parts),
        "suppliers": len(bundle.suppliers),
        "quotes": len(bundle.quotes),
        "inventories": len(bundle.inventories),
        "drafts": len(bundle.drafts),
        "orders": len(bundle.orders),
        "warehouses": len(warehouses),
    }
    return {
        "schema_version": 1,
        "fixture_version": fixture_version,
        "fixed_now": FIXED_NOW.isoformat().replace("+00:00", "Z"),
        "counts": counts,
        "warehouse_summary": warehouse_summary,
        "total_summary": _summary_for(bundle.inventories, None).model_dump(mode="json"),
        "canonical_hash": canonical_hash(bundle),
    }


def load_manifest(fixture_dir: Path = DEFAULT_FIXTURE_DIR) -> dict[str, Any]:
    path = fixture_dir / "manifest.json"
    if not path.is_file():
        raise SeedError(f"manifest not found: {path}; run --write-manifest")
    return json.loads(path.read_text(encoding="utf-8"))


def verify_manifest(bundle: FixtureBundle, manifest: dict[str, Any]) -> None:
    expected = build_manifest(bundle, fixture_version=manifest.get("fixture_version", "v1"))
    if expected != manifest:
        raise SeedError(
            "fixtures/v1/manifest.json does not match fixture data; "
            "run 'uv run python -m scripts.seed --write-manifest' and review the diff"
        )


def write_manifest(fixture_dir: Path = DEFAULT_FIXTURE_DIR) -> dict[str, Any]:
    bundle = load_bundle(fixture_dir)
    manifest = build_manifest(bundle)
    path = fixture_dir / "manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _to_document(model: BaseModel) -> dict[str, Any]:
    document = model.model_dump()
    model_id = document.pop("id")
    document["_id"] = model_id
    return document


async def seed(
    database: AsyncDatabase,
    fixture_dir: Path = DEFAULT_FIXTURE_DIR,
    *,
    reset: bool = False,
) -> SeedSummary:
    if reset and not database.name.startswith(TEST_DB_PREFIX):
        raise SeedError(f"--reset is only allowed for {TEST_DB_PREFIX}* databases")
    bundle = load_bundle(fixture_dir)
    manifest = load_manifest(fixture_dir)
    verify_manifest(bundle, manifest)

    if reset:
        for collection in P01_COLLECTIONS:
            await database.drop_collection(collection)

    await ensure_indexes(database)
    collections = {
        PARTS: bundle.parts,
        SUPPLIERS: bundle.suppliers,
        QUOTES: bundle.quotes,
        INVENTORIES: bundle.inventories,
        DRAFTS: bundle.drafts,
        ORDERS: bundle.orders,
    }
    for name, records in collections.items():
        for record in records:
            document = _to_document(record)
            # 默认 seed 只补缺失的固定合成记录；已有记录（包括用户修改/新增业务数据）一律保留。
            await database[name].update_one(
                {"_id": document["_id"]}, {"$setOnInsert": document}, upsert=True
            )

    database_counts = {
        name: await database[name].count_documents({}) for name in collections
    }
    return SeedSummary(
        database=database.name,
        fixture_counts=manifest["counts"],
        database_counts=database_counts,
        canonical_hash=manifest["canonical_hash"],
        fixture_version=manifest["fixture_version"],
        reset=reset,
        collections=list(P01_COLLECTIONS),
    )
