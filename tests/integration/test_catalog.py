"""P01-T02：分页、筛选、详情 404 与汇总。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.app.contracts.common import ErrorCodes


def _records_across_pages(client, path: str, total: int) -> list[dict]:
    records: list[dict] = []
    pages = 0
    while True:
        pages += 1
        separator = "&" if "?" in path else "?"
        response = client.get(f"{path}{separator}page={pages}&page_size=3")
        assert response.status_code == 200, response.text
        body = response.json()["data"]
        records.extend(body["records"])
        if len(records) >= total or body["page"] >= body["pages"]:
            break
    return records


def test_inventory_pagination_covers_all_eight_rows(seeded_client):
    records = _records_across_pages(seeded_client, "/api/inventory", 8)
    assert len(records) == 8
    assert len({record["id"] for record in records}) == 8
    response = seeded_client.get("/api/inventory?page=1&page_size=3")
    assert response.json()["data"]["pages"] == 3
    assert response.json()["data"]["total"] == 8


def test_parts_pagination_and_metadata(seeded_client):
    response = seeded_client.get("/api/parts?page=1&page_size=3")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["total"] == 6
    assert body["data"]["pages"] == 2
    assert len(body["data"]["records"]) == 3
    assert body["meta"]["data_source"] == "local_seed"
    assert body["meta"]["scope"] == "shared_catalog"
    assert body["meta"]["as_of"]


def test_filter_and_total_are_from_same_scope(seeded_client):
    response = seeded_client.get(
        "/api/inventory?warehouse_id=W01&part_name=刹车片&page=1&page_size=10"
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["total"] == 1
    assert body["records"][0]["id"] == "I001"

    quotes = seeded_client.get(
        "/api/quotes?part_name=刹车片&page=1&page_size=10"
    ).json()["data"]
    assert quotes["total"] == 3
    assert {quote["id"] for quote in quotes["records"]} == {"Q01", "Q02", "Q03"}
    validity = {quote["id"]: quote["is_valid"] for quote in quotes["records"]}
    assert validity == {"Q01": True, "Q02": True, "Q03": False}


def test_empty_search_is_success(seeded_client):
    response = seeded_client.get("/api/parts?name=不存在")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["records"] == []
    assert body["total"] == 0
    assert body["pages"] == 0


def test_invalid_pagination_is_422(seeded_client):
    for path in ("/api/inventory?page=0", "/api/inventory?page_size=101"):
        response = seeded_client.get(path)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == ErrorCodes.VALIDATION_ERROR


def test_unknown_ids_are_404(seeded_client):
    response = seeded_client.get("/api/parts?part_id=NOPE")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == ErrorCodes.NOT_FOUND
    response = seeded_client.get("/api/suppliers?supplier_id=NOPE")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == ErrorCodes.NOT_FOUND


def test_summary_matches_seed_manifest(seeded_client):
    manifest = json.loads(
        (Path(__file__).resolve().parents[2] / "fixtures" / "v1" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    response = seeded_client.get("/api/inventory/summary")
    assert response.status_code == 200
    data = response.json()["data"]
    expected = manifest["total_summary"]
    for key in (
        "records",
        "warehouses",
        "total_on_hand",
        "total_reserved",
        "total_inbound",
        "total_available",
        "total_projected",
        "total_safety_stock",
        "total_target_stock",
        "total_shortage",
        "warning_count",
    ):
        assert data[key] == expected[key]


def test_catalog_requires_local_session(client):
    response = client.get("/api/parts")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == ErrorCodes.UNAUTHENTICATED
