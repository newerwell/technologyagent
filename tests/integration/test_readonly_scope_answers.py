"""P03 scope regressions covered by the P06-fix2 acceptance work."""

import pytest

from backend.app.agent.scripted_model import ScriptedModel, call_tool, token
from tests.integration.test_agent_tools import _run


@pytest.mark.asyncio
async def test_target_replenishment_is_not_satisfied_by_warning_subset(db_name, mongo_admin):
    try:
        model = ScriptedModel(steps=[
            [call_tool("inventory_warning", {"warehouse_id": "W01", "page": 1, "page_size": 50})],
            [token("P001/W01缺口55件；P003/W01缺口36件。")],
            [call_tool("inventory_page", {"warehouse_id": "W01", "page": 1, "page_size": 50})],
            [token("P001/W01缺口55件；P003/W01缺口36件；P004/W01缺口10件。")],
        ])
        outcome, sink, _mongo = await _run(db_name, model, message="W01有哪些零件需要补货？")

        reviews = [payload for kind, payload in sink.events if kind == "review"]
        tokens = [payload["delta"] for kind, payload in sink.events if kind == "token"]
        assert outcome.status == "completed", (outcome, reviews)
        assert len(reviews) == 2 and reviews[0]["passed"] is False and reviews[1]["passed"] is True, [
            [(c["check_id"], c["passed"], c["reason"]) for c in item["details"] if not c["passed"]]
            for item in reviews
        ] + [validate_business_claims(outcome.summary, outcome.evidence).violations,
             [(f.get("field"), f.get("value"), f.get("unit"), f.get("part_id"), f.get("warehouse_id"), f.get("supplier_id"))
              for f in outcome.evidence if f.get("field") in {"unit_price_cents", "total_cents", "line_total_cents", "order_total_cents"}]]
        assert len(tokens) == 1 and "P004/W01缺口10件" in tokens[0]
        plan = [payload for kind, payload in sink.events if kind == "plan"][-1]
        assert plan["items"][0]["status"] == "done"
        assert plan["items"][0]["query_evidence"][-1]["tool_name"] == "inventory_page"
    finally:
        mongo_admin.drop_database(db_name)


@pytest.mark.asyncio
async def test_seven_day_recommendation_requires_replenishment_preview_arguments(db_name, mongo_admin):
    try:
        model = ScriptedModel(steps=[
            [call_tool("quote_list", {"part_id": "P001", "page": 1, "page_size": 50})],
            [token("推荐S01，交期5天。")],
            [call_tool("replenishment_preview", {
                "part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7,
            })],
            [token("P001/W01/S01的交期是5天。")],
        ])
        outcome, sink, _mongo = await _run(
            db_name, model, message="推荐P001在W01七天内到货的供应商。"
        )

        reviews = [payload for kind, payload in sink.events if kind == "review"]
        assert outcome.status == "completed", (outcome, reviews)
        assert len(reviews) == 2 and reviews[0]["passed"] is False and reviews[1]["passed"] is True, [
            [(c["check_id"], c["passed"], c["reason"]) for c in item["details"] if not c["passed"]]
            for item in reviews
        ]
        plan = [payload for kind, payload in sink.events if kind == "plan"][-1]
        query = plan["items"][0]["query_evidence"][-1]
        assert query["tool_name"] == "replenishment_preview"
        assert query["arguments"]["max_lead_days"] == 7
        assert query["arguments"]["part_ids"] == ["P001"]
        assert query["arguments"]["warehouse_id"] == "W01"
    finally:
        mongo_admin.drop_database(db_name)
