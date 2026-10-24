"""P04 草稿边界：字段不足不猜测，金额和版本均由服务端确定。"""

from __future__ import annotations


def test_missing_warehouse_is_reported_without_creating_draft(seeded_client):
    before = seeded_client.get("/api/orders?page=1&page_size=100")
    response = seeded_client.post(
        "/api/drafts",
        json={"part_ids": ["P001"], "max_lead_days": 7},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["missing_fields"] == ["warehouse_id"]
    assert data["drafts"] == []
    after = seeded_client.get("/api/orders?page=1&page_size=100")
    assert after.json()["data"]["total"] == before.json()["data"]["total"]


def test_prepare_and_patch_reprices_with_server_facts(seeded_client):
    prepared = seeded_client.post(
        "/api/drafts",
        json={"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
    )
    assert prepared.status_code == 200, prepared.text
    draft = prepared.json()["data"]["drafts"][0]
    assert (draft["supplier_id"], draft["warehouse_id"], draft["version"]) == ("S01", "W01", 1)
    assert (draft["items"][0]["quantity"], draft["total_cents"]) == (55, 66000)

    patched = seeded_client.patch(
        f"/api/drafts/{draft['id']}",
        json={
            "expected_version": 1,
            "items": [{"part_id": "P001", "quote_id": "Q01", "quantity": 60}],
        },
    )
    assert patched.status_code == 200, patched.text
    changed = patched.json()["data"]
    assert (changed["version"], changed["total_cents"]) == (2, 72000)

    stale = seeded_client.patch(
        f"/api/drafts/{draft['id']}",
        json={
            "expected_version": 1,
            "items": [{"part_id": "P001", "quote_id": "Q01", "quantity": 55}],
        },
    )
    assert stale.status_code == 409


def test_invalid_quote_and_quantity_are_rejected(seeded_client):
    response = seeded_client.post(
        "/api/drafts",
        json={
            "part_ids": ["P001"],
            "warehouse_id": "W01",
            "max_lead_days": 7,
            "quantities": {"P001": 0},
        },
    )
    assert response.status_code == 422


def test_fractional_quantity_is_not_coerced(seeded_client):
    response = seeded_client.post("/api/drafts", json={
        "part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7,
        "quantities": {"P001": 55.5},
    })
    assert response.status_code == 422


def test_duplicate_part_quote_lines_are_merged_before_total_is_saved(seeded_client):
    draft = seeded_client.post("/api/drafts", json={
        "part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7,
    }).json()["data"]["drafts"][0]
    response = seeded_client.patch(f"/api/drafts/{draft['id']}", json={
        "expected_version": 1,
        "items": [
            {"part_id": "P001", "quote_id": "Q01", "quantity": 30},
            {"part_id": "P001", "quote_id": "Q01", "quantity": 30},
        ],
    })
    assert response.status_code == 200, response.text
    updated = response.json()["data"]
    assert len(updated["items"]) == 1
    assert (updated["items"][0]["quantity"], updated["total_cents"]) == (60, 72000)


def test_unknown_part_never_creates_an_approvable_draft(seeded_client):
    response = seeded_client.post("/api/drafts", json={
        "part_ids": ["P999"], "warehouse_id": "W01", "max_lead_days": 7,
    })
    assert response.status_code == 200, response.text
    assert response.json()["data"]["drafts"] == []
    assert response.json()["data"]["missing_fields"] == ["part"]


def test_patch_rejects_expired_quote_and_inactive_supplier(seeded_client):
    from pymongo import MongoClient

    draft = seeded_client.post("/api/drafts", json={
        "part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7,
    }).json()["data"]["drafts"][0]
    expired = seeded_client.patch(f"/api/drafts/{draft['id']}", json={
        "expected_version": 1,
        "items": [{"part_id": "P001", "quote_id": "Q03", "quantity": 55}],
    })
    assert expired.status_code == 422
    container = seeded_client.app.state.container
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        sync[container.settings.mongodb_database]["suppliers"].update_one(
            {"_id": "S01"}, {"$set": {"status": "inactive"}}
        )
    finally:
        sync.close()
    inactive = seeded_client.patch(f"/api/drafts/{draft['id']}", json={
        "expected_version": 1,
        "items": [{"part_id": "P001", "quote_id": "Q01", "quantity": 55}],
    })
    assert inactive.status_code == 422
    unchanged = seeded_client.get(f"/api/drafts/{draft['id']}").json()["data"]
    assert (unchanged["version"], unchanged["total_cents"]) == (1, 66000)
