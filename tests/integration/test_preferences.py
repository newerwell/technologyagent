from backend.app.api.dependencies import get_context
from backend.app.contracts.common import RequestContext


def _data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_only_explicit_preferences_are_persisted_scoped_and_applied(seeded_client):
    saved = _data(seeded_client.put("/api/preferences", json={
        "key": "default_warehouse", "value": "W01", "remember": True,
    }))
    assert saved["explicit"] is True
    assert _data(seeded_client.get("/api/preferences")) == {"default_warehouse": "W01"}
    supplier = _data(seeded_client.put("/api/preferences", json={
        "key": "preferred_supplier", "value": "S01", "remember": True,
    }))
    assert supplier["value"] == "S01"
    lead_days = _data(seeded_client.put("/api/preferences", json={
        "key": "max_lead_days", "value": 7, "remember": True,
    }))
    assert lead_days["value"] == 7
    assert _data(seeded_client.get("/api/preferences"))["max_lead_days"] == 7

    implicit = seeded_client.put("/api/preferences", json={
        "key": "default_warehouse", "value": "W02",
    })
    assert implicit.status_code == 422

    owner_b = RequestContext(owner_id="owner-b", request_id="owner-b")
    seeded_client.app.dependency_overrides[get_context] = lambda: owner_b
    try:
        assert _data(seeded_client.get("/api/preferences")) == {}
    finally:
        seeded_client.app.dependency_overrides.pop(get_context, None)

    preferred = _data(seeded_client.post("/api/order-workflows", json={
        "message": "prepare P001", "request_id": "preference-default-warehouse",
        "draft": {"part_ids": ["P001"], "max_lead_days": 7},
    }))
    assert preferred["status"] == "waiting_input"
    draft = _data(seeded_client.get(f"/api/drafts/{preferred['pending_interrupt']['draft_id']}"))
    assert draft["warehouse_id"] == "W01"

    explicit = _data(seeded_client.post("/api/order-workflows", json={
        "message": "prepare P001", "request_id": "preference-explicit-warehouse",
        "draft": {"part_ids": ["P001"], "warehouse_id": "W02", "max_lead_days": 7, "quantities": {"P001": 55}},
    }))
    assert explicit["status"] == "waiting_input", explicit
    from pymongo import MongoClient
    container = seeded_client.app.state.container
    sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
    try:
        stored_run = sync[container.settings.mongodb_database]["runs"].find_one({"_id": explicit["id"]})
        assert stored_run["order_intent"]["warehouse_id"] == "W02"
    finally:
        sync.close()

    cleared = _data(seeded_client.delete("/api/preferences/default_warehouse"))
    assert cleared["deleted"] is True
    _data(seeded_client.delete("/api/preferences/preferred_supplier"))
    _data(seeded_client.delete("/api/preferences/max_lead_days"))
    assert _data(seeded_client.get("/api/preferences")) == {}


def test_disabled_or_invalid_supplier_preference_is_rejected(seeded_client):
    response = seeded_client.put("/api/preferences", json={
        "key": "preferred_supplier", "value": "S03", "remember": True,
    })
    assert response.status_code == 422
    bad_days = seeded_client.put("/api/preferences", json={
        "key": "max_lead_days", "value": True, "remember": True,
    })
    assert bad_days.status_code == 422
