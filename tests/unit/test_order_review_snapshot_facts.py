def test_order_review_snapshot_reuses_persisted_order_facts():
    from backend.app.services.order_workflows import _build_order_review_fact_index

    verified_orders = [{
        "operation_id": "operation-1",
        "operation": {"_id": "operation-1", "status": "succeeded", "action": "order_create",
                      "order_id": "persisted-1"},
        "approval": {"_id": "approval-1", "status": "consumed", "decision": "approve",
                     "action": "order_create", "order_id": "persisted-1"},
        "order": {
            "_id": "persisted-1", "number": "PO-20261109-001", "warehouse_id": "W01",
            "supplier_id": "S02", "status": "created", "total_cents": 66000,
            "items": [{"part_id": "P001", "quantity": 55, "unit_price_cents": 1200,
                       "line_total_cents": 66000}],
            "verification_facts": {
                "request_constraints": {"max_lead_days": 7},
                "items": [{"part_id": "P001", "warehouse_id": "W01", "supplier_id": "S02",
                           "unit": "套", "lead_days": 5}],
            },
        },
    }]

    index = _build_order_review_fact_index(verified_orders)
    assert {fact.key.field for fact in index.facts} >= {
        "quantity", "order_total_cents", "total_cents", "lead_days", "max_lead_days",
        "operation_status", "approval_status",
    }
    assert all(fact.call_id == "operation-1" for fact in index.facts)
    assert any(fact.value == 55 and fact.unit == "套" for fact in index.facts)
    assert any(fact.value == 66000 and fact.key.field == "order_total_cents" for fact in index.facts)
