"""P01-T04：补货预览固定案例、缺失数据与响应来源。"""

from __future__ import annotations

from backend.app.contracts.common import ErrorCodes


def _preview(client, **payload):
    body = {"part_ids": ["P001"], "warehouse_id": "W01", **payload}
    return client.post("/api/replenishment/preview", json=body)


def test_p001_price_priority_and_7_day_limit(seeded_client):
    price = _preview(seeded_client)
    assert price.status_code == 200, price.text
    line = price.json()["data"]["lines"][0]
    assert (line["available"], line["projected"], line["shortage"]) == (15, 25, 55)
    assert (line["recommended_quote_id"], line["quantity"], line["total_cents"]) == (
        "Q02",
        55,
        60500,
    )
    assert [quote["quote_id"] for quote in line["candidate_quotes"]] == ["Q02", "Q01"]
    assert line["actionable"] is True
    assert price.json()["meta"]["data_source"] == "local_seed"
    assert price.json()["meta"]["scope"] == "shared_catalog"

    lead = _preview(seeded_client, max_lead_days=7)
    assert lead.status_code == 200
    line = lead.json()["data"]["lines"][0]
    assert (line["recommended_quote_id"], line["quantity"], line["total_cents"]) == (
        "Q01",
        55,
        66000,
    )
    assert [quote["quote_id"] for quote in line["candidate_quotes"]] == ["Q01"]
    assert lead.json()["data"]["snapshot_versions"] == {"I001": 1}
    assert lead.json()["data"]["source_refs"]


def test_p002_threshold_and_p003_missing_quote(seeded_client):
    p002 = seeded_client.post(
        "/api/replenishment/preview",
        json={"part_ids": ["P002"], "warehouse_id": "W02"},
    ).json()["data"]["lines"][0]
    assert p002["projected"] == 15
    assert p002["warning"] is False
    assert p002["shortage"] == 15

    p003 = seeded_client.post(
        "/api/replenishment/preview",
        json={"part_ids": ["P003"], "warehouse_id": "W01"},
    ).json()["data"]["lines"][0]
    assert p003["shortage"] == 36
    assert p003["actionable"] is False
    assert p003["missing_fields"] == ["valid_quote"]
    assert (p003["quantity"], p003["total_cents"]) == (0, 0)


def test_missing_inventory_and_part_are_explicit(seeded_client):
    response = seeded_client.post(
        "/api/replenishment/preview",
        json={"part_ids": ["P006"], "warehouse_id": "W02"},
    )
    line = response.json()["data"]["lines"][0]
    assert line["missing_fields"] == ["inventory"]
    assert line["actionable"] is False

    response = seeded_client.post(
        "/api/replenishment/preview",
        json={"part_ids": ["P999"], "warehouse_id": "W01"},
    )
    line = response.json()["data"]["lines"][0]
    assert line["missing_fields"] == ["part"]
    assert line["actionable"] is False


def test_warnings_and_summary(seeded_client):
    w01 = seeded_client.get("/api/inventory/warnings?warehouse_id=W01").json()["data"]
    assert w01["total"] == 2
    assert {item["id"] for item in w01["records"]} == {"I001", "I005"}
    w02 = seeded_client.get("/api/inventory/warnings?warehouse_id=W02").json()["data"]
    assert w02["total"] == 0
    assert w02["records"] == []

    summary = seeded_client.get("/api/inventory/summary?warehouse_id=W01").json()["data"]
    assert summary["records"] == 5
    assert summary["warning_count"] == 2
    assert summary["total_shortage"] == 101


def test_preview_validation(seeded_client):
    duplicate = seeded_client.post(
        "/api/replenishment/preview",
        json={"part_ids": ["P001", "P001"], "warehouse_id": "W01"},
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == ErrorCodes.VALIDATION_ERROR

    negative = seeded_client.post(
        "/api/replenishment/preview",
        json={"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": -1},
    )
    assert negative.status_code == 422


def test_preview_requires_local_session(client):
    response = client.post(
        "/api/replenishment/preview",
        json={"part_ids": ["P001"], "warehouse_id": "W01"},
    )
    assert response.status_code == 401
