"""P04 approval binding and owner isolation edge cases."""


def test_approval_decision_is_owner_scoped_and_rejection_has_no_write(seeded_client):
    from backend.app.api.dependencies import get_context
    from backend.app.contracts.common import RequestContext

    draft_response = seeded_client.post("/api/drafts", json={
        "part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7,
    })
    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()["data"]["drafts"][0]
    request = seeded_client.post(f"/api/drafts/{draft['id']}/approval", json={"run_id": "owner-scope-run"})
    assert request.status_code == 200, request.text
    approval_id = request.json()["data"]["approval_id"]

    seeded_client.app.dependency_overrides[get_context] = lambda: RequestContext(
        owner_id="owner-b", request_id="owner-b"
    )
    cross_owner = seeded_client.post(f"/api/approvals/{approval_id}/resolve", json={
        "interrupt_id": "owner-scope", "decision": "approve", "expected_version": 1,
        "idempotency_key": "owner-b-approve",
    })
    assert cross_owner.status_code == 404
    seeded_client.app.dependency_overrides.pop(get_context, None)

    rejected = seeded_client.post(f"/api/approvals/{approval_id}/resolve", json={
        "interrupt_id": "owner-scope", "decision": "reject", "expected_version": 1,
        "idempotency_key": "owner-a-reject",
    })
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["status"] == "rejected"
    assert seeded_client.get(f"/api/drafts/{draft['id']}").json()["data"]["state"] == "rejected"
    assert seeded_client.get("/api/orders?page=1&page_size=100").json()["data"]["total"] == 2
