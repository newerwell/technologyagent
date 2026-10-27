"""Stable fingerprints for complete paged read results."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.app.contracts.common import PageQuery


def _fingerprint(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def inventory_page_snapshot_id(runtime, *, warehouse_id: str | None, part_name: str | None,
                                     warning_only: bool, page: int, page_size: int,
                                     response_data: dict[str, Any]) -> str | None:
    """Fingerprint the full filtered source set and ensure the returned page matches it."""
    inventories = await runtime.inventory._repository.list_all(warehouse_id, part_name)
    units = await runtime.inventory._units(inventories)
    rows = [runtime.inventory._view(item, units.get(item.part_id)).model_dump(mode="json") for item in inventories]
    if warning_only:
        rows = [row for row in rows if row.get("warning") is True]
    start = (page - 1) * page_size
    expected = rows[start:start + page_size]
    if (response_data.get("records") != expected or response_data.get("total") != len(rows)
            or response_data.get("pages") != ((len(rows) + page_size - 1) // page_size if rows else 0)):
        return None
    return _fingerprint(rows)


async def quote_page_snapshot_id(runtime, *, part_id: str | None, part_name: str | None,
                                 supplier_id: str | None, page: int, page_size: int,
                                 response_data: dict[str, Any]) -> str | None:
    """Fingerprint all matching quote views and verify this response belongs to them."""
    first = await runtime.catalog.page_quotes(part_name, part_id, supplier_id, PageQuery(page=1, page_size=100))
    rows = [item.model_dump(mode="json") for item in first.records]
    for page_number in range(2, first.pages + 1):
        result = await runtime.catalog.page_quotes(part_name, part_id, supplier_id,
                                                   PageQuery(page=page_number, page_size=100))
        if result.total != first.total or result.pages != first.pages:
            return None
        rows.extend(item.model_dump(mode="json") for item in result.records)
    if len(rows) != first.total:
        return None
    start = (page - 1) * page_size
    expected = rows[start:start + page_size]
    if (response_data.get("records") != expected or response_data.get("total") != first.total
            or response_data.get("pages") != ((first.total + page_size - 1) // page_size if first.total else 0)):
        return None
    return _fingerprint(rows)
