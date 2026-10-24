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


def test_fact_field_and_unit_cannot_be_swapped_between_shortage_and_amount():
    evidence = collect_evidence("replenishment_preview", _preview(), call_id="call-1")
    assert not validate_business_claims("P001 W01 缺口66000件，金额55元", evidence).passed
    assert not validate_business_claims("P001 W01 总额66000元", evidence).passed
    assert validate_business_claims("P001 W01 缺口55件，总额660.00元", evidence).passed


def test_answer_conclusion_cannot_contradict_successful_replenishment_facts():
    evidence = collect_evidence("replenishment_preview", _preview(), call_id="call-1")
    assert not validate_business_claims("P001 在 W01 库存充足，无需补货。", evidence).passed


def test_incidental_dates_versions_and_identifiers_are_not_business_claims():
    evidence = collect_evidence("replenishment_preview", _preview(), call_id="call-1")
    answer = "P001/W01 截至2026-10-24，记录版本1：缺口55件，总额660.00元。"
    assert validate_business_claims(answer, evidence).passed


def test_observation_timestamp_near_inventory_label_is_not_a_stock_claim():
    result = ToolResult(ok=True, data={"records": [{
        "id": "I001", "part_id": "P001", "warehouse_id": "W01", "on_hand": 20,
    }]}, call_id="call-i")
    evidence = collect_evidence("inventory_page", result, call_id="call-i")

    answer = "P001/W01 在手库存观察时间为2026-10-24T11:09:06Z，当前在手库存20件。"

    assert validate_business_claims(answer, evidence).passed


def test_yuan_without_an_explicit_amount_label_is_checked_as_total_cents():
    evidence = collect_evidence("replenishment_preview", _preview(), call_id="call-1")
    assert validate_business_claims("660.00元", evidence).passed


def test_inventory_fields_bind_to_their_own_structured_values():
    result = ToolResult(ok=True, data={"records": [{
        "id": "I001", "part_id": "P001", "warehouse_id": "W01", "on_hand": 20,
        "reserved": 5, "inbound": 10, "safety_stock": 30, "target_stock": 80,
        "available": 15, "projected": 25, "shortage": 55,
    }]}, call_id="call-i")
    evidence = collect_evidence("inventory_page", result, call_id="call-i")
    assert validate_business_claims(
        "P001/W01：在手20件、预留5件、在途10件、目标库存80件、可用15件、缺口55件。", evidence
    ).passed
    assert not validate_business_claims("P001/W01：可用20件。", evidence).passed


def test_shortage_contradictions_are_checked_within_the_claimed_part_scope():
    result = ToolResult(ok=True, data={"lines": [
        {"part_id": "P001", "warehouse_id": "W01", "shortage": 55},
        {"part_id": "P002", "warehouse_id": "W01", "shortage": 0},
    ], "source_refs": [{"entity": "inventory", "id": "I001"}]}, call_id="call-i")
    evidence = collect_evidence("replenishment_preview", result, call_id="call-i")
    assert validate_business_claims(
        "P001/W01缺口55件；P002/W01库存充足，无需补货。", evidence
    ).passed
    assert not validate_business_claims("P001/W01缺口55件；P001库存充足，无需补货。", evidence).passed


def test_model_and_tool_timeouts_are_bounded_by_remaining_run_time():
    now = [0.0]
    budget = RunBudget("r", max_active_seconds=180, monotonic=lambda: now[0])
    assert budget.bounded_timeout(60) == 60
    now[0] = 179
    assert budget.bounded_timeout(60) == 1
    assert budget.bounded_timeout(15) == 1
    now[0] = 180
    assert budget.bounded_timeout(60) == 0
