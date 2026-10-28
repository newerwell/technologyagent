import json

import pytest

from backend.app.contracts.domain import InventoryQuery
from backend.app.integrations.inventory_snapshot import InventorySnapshot, SnapshotInventoryService


@pytest.fixture
def snapshot_file(tmp_path):
    path = tmp_path / "inventory_snapshot.json"
    records = [
        {"id": 1, "partId": 10, "currentQuantity": 3, "safetyStock": 5,
         "warehouseLocation": "A区-1号库", "deleted": 0,
         "partDetail": {"id": 10, "partCode": "BRAKE", "name": "刹车片", "unit": "片"}},
        {"id": 2, "partId": 20, "currentQuantity": 8, "safetyStock": 5,
         "warehouseLocation": "B区-2号库", "deleted": 0,
         "partDetail": {"id": 20, "partCode": "BOLT", "name": "螺丝", "unit": "个"}},
    ]
    path.write_text(json.dumps({"code": 200, "timestamp": 1792744281356,
        "data": {"current": 1, "size": 10, "total": 0, "pages": 0, "records": records}},
        ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_snapshot_preserves_unknown_fields_and_recomputes_pagination(snapshot_file):
    source = InventorySnapshot(snapshot_file)
    service = SnapshotInventoryService(source)
    page = await service.page(InventoryQuery(page=1, page_size=1))
    assert (page.total, page.pages, len(page.records)) == (2, 2, 1)
    row = page.records[0]
    assert row.on_hand == 3 and row.safety_stock == 5 and row.warning is True
    assert row.reserved is None and row.inbound is None and row.target_stock is None
    assert row.shortage is None and row.projected is None and row.available is None
    assert row.safety_shortage == 2 and row.warehouse_id == "A区-1号库"
    assert source.metadata["reported_source_total"] == 0
    assert source.metadata["completeness"] == "unknown"
    assert page.source_refs and source.metadata["snapshot_id"]


@pytest.mark.asyncio
async def test_filter_warning_and_empty_result_remain_sourced(snapshot_file):
    service = SnapshotInventoryService(InventorySnapshot(snapshot_file))
    page = await service.page(InventoryQuery(part_name="刹车", warehouse_id="A区-1号库"))
    assert page.total == 1 and page.records[0].part_id == "10"
    warnings = await service.warnings(InventoryQuery())
    assert warnings.total == 1
    empty = await service.warnings(InventoryQuery(warehouse_id="B区-2号库"))
    assert empty.total == 0 and empty.pages == 0 and empty.source_refs
    summary = await service.summary()
    assert summary.total_on_hand == 11 and summary.total_shortage is None
    assert summary.warning_count == 1


def test_corrupt_snapshot_never_falls_back_to_seed(snapshot_file):
    snapshot_file.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot"):
        InventorySnapshot(snapshot_file)
