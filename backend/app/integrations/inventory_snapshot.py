"""Read-only ERP inventory file adapter. Never fabricates missing stock fields."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from backend.app.contracts.common import AppError, Page, make_page
from backend.app.contracts.domain import InventoryQuery, Part


class SnapshotInventoryView(BaseModel):
    id: str
    part_id: str
    part_name: str
    warehouse_id: str
    unit: str
    on_hand: int = Field(ge=0)
    safety_stock: int = Field(ge=0)
    warning: bool
    safety_shortage: int = Field(ge=0)
    reserved: int | None = None
    inbound: int | None = None
    available: int | None = None
    projected: int | None = None
    target_stock: int | None = None
    shortage: int | None = None
    version: int | None = None
    missing_fields: list[str] = Field(default_factory=lambda: [
        "reserved", "inbound", "available", "projected", "target_stock", "shortage", "version"])


class SnapshotPage(Page[SnapshotInventoryView]):
    source_refs: list[dict[str, str]]


class SnapshotSummary(BaseModel):
    warehouse_id: str | None = None
    records: int
    warehouses: int
    total_on_hand: int
    total_safety_stock: int
    warning_count: int
    total_reserved: int | None = None
    total_inbound: int | None = None
    total_available: int | None = None
    total_projected: int | None = None
    total_target_stock: int | None = None
    total_shortage: int | None = None
    source_refs: list[dict[str, str]]


class InventorySnapshot:
    def __init__(self, path: Path):
        self.path = path
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8-sig"))
            if payload.get("code") != 200 or not isinstance(payload.get("data", {}).get("records"), list):
                raise ValueError("invalid response envelope")
            data = payload["data"]
            metadata_path = path.with_suffix(".meta.json")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig")) if metadata_path.exists() else {}
            self.as_of = (datetime.fromisoformat(metadata["fetched_at"].replace("Z", "+00:00"))
                          if metadata.get("fetched_at") else datetime.fromtimestamp(payload["timestamp"] / 1000, timezone.utc))
            if self.as_of.tzinfo is None:
                raise ValueError("snapshot time must contain timezone")
            self.sha256 = hashlib.sha256(raw).hexdigest()
            self.parts: dict[str, Part] = {}
            self.rows: list[SnapshotInventoryView] = []
            ids: set[str] = set()
            for row in data["records"]:
                if row.get("deleted", 0) != 0:
                    continue
                detail = row["partDetail"]
                if detail.get("deleted", 0) != 0:
                    continue
                if str(row["partId"]) != str(detail["id"]):
                    raise ValueError("part identity mismatch")
                part = Part(id=str(detail["id"]), code=detail["partCode"], name=detail["name"],
                            unit=detail["unit"], specification=detail.get("specification") or "",
                            category=detail.get("category") or "")
                if part.id in self.parts and self.parts[part.id] != part:
                    raise ValueError("conflicting part identity")
                self.parts[part.id] = part
                count, safety = row["currentQuantity"], row["safetyStock"]
                if type(count) is not int or type(safety) is not int or min(count, safety) < 0:
                    raise ValueError("invalid stock quantity")
                record_id = str(row["id"])
                if record_id in ids or not str(row["warehouseLocation"]).strip():
                    raise ValueError("duplicate inventory identity or missing warehouse")
                ids.add(record_id)
                self.rows.append(SnapshotInventoryView(id=record_id, part_id=part.id, part_name=part.name,
                    unit=part.unit, warehouse_id=row["warehouseLocation"], on_hand=count, safety_stock=safety,
                    warning=count < safety, safety_shortage=max(0, safety - count)))
            self.metadata = {"data_source": "local_snapshot", "as_of": self.as_of.isoformat(),
                "scope": "captured_inventory_snapshot", "snapshot_id": self.sha256,
                "record_count": len(self.rows), "reported_source_total": data.get("total"),
                "warehouses": sorted({row.warehouse_id for row in self.rows}),
                "reported_source_pages": data.get("pages"), "completeness": "unknown",
                "source_file": path.name, "read_only": True}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"inventory snapshot unavailable or invalid: {path.name} ({type(exc).__name__})") from exc

    @property
    def refs(self):
        return [{"entity": "inventory_snapshot", "id": self.sha256,
                 "data_source": "local_snapshot", "as_of": self.as_of.isoformat()}]


class SnapshotInventoryService:
    def __init__(self, source: InventorySnapshot):
        self.source = source
        self._repository = self

    @property
    def snapshot_meta(self):
        return dict(self.source.metadata)

    async def list_all(self, warehouse_id=None, part_name=None):
        return [row for row in self.source.rows
                if (not warehouse_id or row.warehouse_id == warehouse_id)
                and (not part_name or part_name.casefold() in row.part_name.casefold())]

    def _view(self, row, unit=None):
        return row

    async def _units(self, rows):
        return {row.part_id: row.unit for row in rows}

    async def page(self, query: InventoryQuery):
        rows = await self.list_all(query.warehouse_id, query.part_name)
        return self._page(rows, query)

    def _page(self, rows, query):
        start = (query.page - 1) * query.page_size
        page = make_page(rows[start:start + query.page_size], len(rows), query.page, query.page_size)
        return SnapshotPage(**page.model_dump(), source_refs=self.source.refs)

    async def warnings(self, query: InventoryQuery):
        rows = [row for row in await self.list_all(query.warehouse_id, query.part_name) if row.warning]
        return self._page(rows, query)

    async def get(self, inventory_id: str):
        for row in self.source.rows:
            if row.id == inventory_id:
                return row
        raise AppError("NOT_FOUND", "inventory not found in local snapshot", 404)

    async def summary(self, warehouse_id=None):
        rows = await self.list_all(warehouse_id)
        return SnapshotSummary(warehouse_id=warehouse_id, records=len(rows),
            warehouses=len({row.warehouse_id for row in rows}), total_on_hand=sum(row.on_hand for row in rows),
            total_safety_stock=sum(row.safety_stock for row in rows), warning_count=sum(row.warning for row in rows),
            source_refs=self.source.refs)


class SnapshotCatalogRepository:
    def __init__(self, source: InventorySnapshot, fallback):
        self.source, self.fallback = source, fallback

    def __getattr__(self, name):
        return getattr(self.fallback, name)

    async def search_parts(self, name, query):
        rows = [p for p in self.source.parts.values() if not name or name.casefold() in p.name.casefold()]
        start = (query.page - 1) * query.page_size
        return make_page(rows[start:start + query.page_size], len(rows), query.page, query.page_size)

    async def get_part(self, part_id):
        if part_id not in self.source.parts:
            raise AppError("NOT_FOUND", "part not found in local inventory snapshot", 404)
        return self.source.parts[part_id]

    async def list_parts(self, part_ids):
        return [p for p in self.source.parts.values() if p.id in part_ids]

    async def page_quotes(self, *args, **kwargs):
        raise AppError("UNSUPPORTED_OPERATION", "库存快照不含有效供应商报价、交期和MOQ。", 405)

    async def list_quotes(self, *args, **kwargs):
        raise AppError("UNSUPPORTED_OPERATION", "库存快照不含有效供应商报价、交期和MOQ。", 405)


class SnapshotReplenishmentService:
    async def preview(self, *args, **kwargs):
        raise AppError("UNSUPPORTED_OPERATION", "库存快照缺少预留量、在途量、目标库存与供应商报价，不能计算目标补货或创建订单。", 405)


def build_read_services(settings, catalog_repo, inventory_repo, clock):
    from backend.app.services.catalog import CatalogService, InventoryService
    from backend.app.services.replenishment import ReplenishmentService
    if settings.inventory_snapshot_path is not None:
        if settings.inventory_data_source != "local_snapshot" or settings.parts_data_source != "local_snapshot":
            raise ValueError("INVENTORY_SNAPSHOT_PATH requires INVENTORY/PARTS_DATA_SOURCE=local_snapshot")
        source = InventorySnapshot(settings.resolved_inventory_snapshot_path)
        catalog_repo = SnapshotCatalogRepository(source, catalog_repo)
        return catalog_repo, CatalogService(catalog_repo, clock), SnapshotInventoryService(source), SnapshotReplenishmentService()
    return (catalog_repo, CatalogService(catalog_repo, clock), InventoryService(inventory_repo, catalog_repo),
            ReplenishmentService(catalog_repo, inventory_repo, clock))
