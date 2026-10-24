from backend.app.agent.evidence import collect_evidence, validate_business_claims
from backend.app.ports.tools import ToolResult
from backend.app.agent.budget import RunBudget


def _preview(part_id="P001", warehouse_id="W01", shortage=55, total_cents=66000):
    return ToolResult(
        ok=True,
        data={
            "lines": [{
                "part_id": part_id,
                "warehouse_id": warehouse_id,
                "inventory_id": "inv-1",
                "shortage": shortage,
                "version": 1,
                "quantity": 55,
                "total_cents": total_cents,
            }],
            "source_refs": [{"entity": "inventory", "id": "inv-1", "as_of": "2026-10-24T00:00:00Z"}],
        },
        meta={"data_source": "local_seed", "as_of": "2026-10-24T00:00:00Z"},
        call_id="call-1",
    )


def test_claim_values_must_match_successful_facts_and_entity_scope():
    evidence = collect_evidence("replenishment_preview", _preview(), call_id="call-1")
    assert validate_business_claims("P001 在 W01 缺口55件，总额660.00元", evidence).passed
    assert not validate_business_claims("P001 在 W01 缺口999件", evidence).passed
    assert not validate_business_claims("P002 在 W02 缺口55件", evidence).passed
    assert not validate_business_claims("P001 在 W01 缺口1件", evidence).passed
    assert not validate_business_claims("缺口999999分", evidence).passed
    assert not validate_business_claims("55", evidence).passed


def test_unrelated_reference_and_failed_tool_do_not_support_numeric_claim():
    unrelated = collect_evidence(
        "supplier_get",
        ToolResult(ok=True, data={"id": "S01", "lead_days": 5}, call_id="call-s"),
        call_id="call-s",
    )
    assert not validate_business_claims("P001 在 W01 缺口55", unrelated).passed
    assert collect_evidence(
        "inventory_get", ToolResult(ok=False, data={"id": "inv-1", "shortage": 55}), call_id="bad"
    ) == []


def test_model_and_tool_timeouts_are_bounded_by_remaining_run_time():
    now = [0.0]
    budget = RunBudget("r", max_active_seconds=180, monotonic=lambda: now[0])
    assert budget.bounded_timeout(60) == 60
    now[0] = 179
    assert budget.bounded_timeout(60) == 1
    assert budget.bounded_timeout(15) == 1
    now[0] = 180
    assert budget.bounded_timeout(60) == 0
