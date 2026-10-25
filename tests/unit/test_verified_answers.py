from backend.app.agent.verified_answers import render_verified_core_facts
from backend.app.contracts.workflow import PlanItem


def test_target_gap_answer_is_rendered_from_complete_scoped_facts():
    state = {
        "request_constraints": {"warehouse_ids": ["W01"], "part_ids": [], "intent": "target_replenishment"},
        "plan": [PlanItem(id="inventory", title="库存", status="done", query_evidence=[
            {"call_id": "i", "tool_name": "inventory_page", "data_source": "local_seed",
             "arguments": {"warehouse_id": "W01", "page": 1, "page_size": 50},
             "as_of": "2026-10-25T04:00:00Z", "total": 2, "page": 1, "pages": 1,
             "record_ids": ["I001", "I004"]},
        ]).model_dump(mode="json")],
        "evidence": [
            {"call_id": "i", "field": "shortage", "value": 55, "unit": "count", "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "i", "field": "shortage", "value": 10, "unit": "count", "part_id": "P004", "warehouse_id": "W01"},
        ],
    }

    answer = render_verified_core_facts(state)

    assert answer == "W01的P001目标库存缺口为55件；W01的P004目标库存缺口为10件。补货判定采用目标库存缺口口径，与安全库存预警口径不同。\n数据源：local_seed；观察时间：2026-10-25T04:00:00Z。"


def test_seven_day_supplier_answer_uses_the_service_selected_quote_and_bound_fields():
    state = {
        "request_constraints": {"warehouse_ids": [], "part_ids": [], "max_lead_days": 7,
                                "intent": "supplier_recommendation"},
        "plan": [PlanItem(id="supplier", title="报价", status="done", query_evidence=[
            {"call_id": "preview", "tool_name": "replenishment_preview", "data_source": "local_seed",
             "arguments": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
             "as_of": "2026-10-25T04:00:00Z"},
        ]).model_dump(mode="json")],
        "evidence": [
            {"call_id": "preview", "field": "max_lead_days", "value": 7, "unit": "days", "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "preview", "field": "recommended_quote_id", "value": "Q01", "unit": "identifier", "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "preview", "field": "quote_id", "value": "Q01", "unit": "identifier", "part_id": "P001", "warehouse_id": "W01", "supplier_id": "S01"},
            {"call_id": "preview", "field": "unit", "value": "套", "unit": "label", "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "preview", "field": "lead_days", "value": 5, "unit": "days", "part_id": "P001", "warehouse_id": "W01", "supplier_id": "S01"},
            {"call_id": "preview", "field": "quantity", "value": 55, "unit": "count", "part_id": "P001", "warehouse_id": "W01", "supplier_id": "S01"},
            {"call_id": "preview", "field": "unit_price_cents", "value": 1200, "unit": "cents", "part_id": "P001", "warehouse_id": "W01", "supplier_id": "S01"},
            {"call_id": "preview", "field": "total_cents", "value": 66000, "unit": "cents", "part_id": "P001", "warehouse_id": "W01", "supplier_id": "S01"},
        ],
    }

    answer = render_verified_core_facts(state)

    assert answer == "服务推荐报价Q01：P001/W01/S01交期5天；P001/W01数量55套；P001/W01/S01单价12.00元/套；P001/W01总额660.00元；P001/W01符合用户提出的7天内到货条件。\n数据源：local_seed；观察时间：2026-10-25T04:00:00Z。"


def test_cheapest_supplier_answer_is_rendered_only_after_complete_invalid_quote_query():
    state = {
        "request_constraints": {"warehouse_ids": [], "part_ids": ["P003"], "intent": "supplier_recommendation"},
        "plan": [PlanItem(id="supplier", title="报价", status="done", query_evidence=[
            {"call_id": "quotes", "tool_name": "quote_list", "data_source": "local_seed",
             "arguments": {"part_id": "P003", "page": 1, "page_size": 50},
             "as_of": "2026-10-25T04:00:00Z", "total": 1, "page": 1, "pages": 1,
             "record_ids": ["Q06"]},
        ]).model_dump(mode="json")],
        "evidence": [
            {"call_id": "quotes", "field": "is_valid", "value": False, "unit": "boolean", "part_id": "P003", "supplier_id": "S03", "id": "Q06"},
        ],
    }

    answer = render_verified_core_facts(state)

    assert answer == "P003没有有效报价，无法判断最便宜的供应商。\n数据源：local_seed；观察时间：2026-10-25T04:00:00Z。"


def test_seven_day_report_core_covers_inventory_facts_quote_tradeoff_and_artifact():
    state = {
        "request_constraints": {"warehouse_ids": ["W01"], "part_ids": ["P001"], "max_lead_days": 7,
                                "intent": "supplier_recommendation"},
        "plan": [
            PlanItem(id="preview", title="筛选补货报价", status="done", query_evidence=[{
                "call_id": "preview", "tool_name": "replenishment_preview", "data_source": "local_seed",
                "arguments": {"part_ids": ["P001"], "warehouse_id": "W01", "max_lead_days": 7},
                "as_of": "2026-10-25T04:00:00Z",
            }]).model_dump(mode="json"),
            PlanItem(id="quotes", title="比较报价", status="done", query_evidence=[{
                "call_id": "quotes", "tool_name": "quote_list", "data_source": "local_seed",
                "arguments": {"part_id": "P001", "page": 1, "page_size": 50},
                "as_of": "2026-10-25T04:00:00Z", "total": 3, "page": 1, "pages": 1,
                "record_ids": ["Q01", "Q02", "Q03"],
            }]).model_dump(mode="json"),
        ],
        "evidence": [
            {"call_id": "preview", "field": "recommended_quote_id", "value": "Q01", "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "preview", "field": "quote_id", "value": "Q01", "part_id": "P001", "warehouse_id": "W01", "supplier_id": "S01"},
            {"call_id": "preview", "field": "unit", "value": "套", "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "preview", "field": "quantity", "value": 55, "part_id": "P001", "warehouse_id": "W01", "supplier_id": "S01"},
            {"call_id": "preview", "field": "lead_days", "value": 5, "part_id": "P001", "warehouse_id": "W01", "supplier_id": "S01"},
            {"call_id": "preview", "field": "unit_price_cents", "value": 1200, "part_id": "P001", "warehouse_id": "W01", "supplier_id": "S01"},
            {"call_id": "preview", "field": "total_cents", "value": 66000, "part_id": "P001", "warehouse_id": "W01", "supplier_id": "S01"},
            {"call_id": "inventory", "field": "on_hand", "value": 20, "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "inventory", "field": "reserved", "value": 5, "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "inventory", "field": "inbound", "value": 10, "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "inventory", "field": "available", "value": 15, "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "inventory", "field": "projected", "value": 25, "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "inventory", "field": "shortage", "value": 55, "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "inventory", "field": "warning", "value": True, "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "inventory", "field": "safety_stock", "value": 30, "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "inventory", "field": "target_stock", "value": 80, "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "quotes", "field": "lead_days", "value": 12, "id": "Q02", "part_id": "P001", "supplier_id": "S02"},
            {"call_id": "quotes", "field": "unit_price_cents", "value": 1100, "id": "Q02", "part_id": "P001", "supplier_id": "S02"},
            {"call_id": "quotes", "field": "is_valid", "value": True, "id": "Q02", "part_id": "P001", "supplier_id": "S02"},
            {"call_id": "artifact", "field": "artifact_id", "value": "art_1", "entity": "artifact"},
            {"call_id": "artifact", "field": "filename", "value": "analysis.md", "entity": "artifact"},
        ],
    }
    answer = render_verified_core_facts(state)
    assert answer is not None
    assert "在手20套" in answer and "预留5套" in answer and "在途10套" in answer
    assert "可用15套" in answer and "预计可用25套" in answer and "目标缺口55套" in answer
    assert "安全库存30套" in answer and "目标库存80套" in answer and "预警" in answer
    assert "Q01" in answer and "5天" in answer and "12.00元/套" in answer
    assert "Q02" in answer and "11.00元/套" in answer and "超出7天" in answer
    assert "事实" in answer and "建议" in answer and "快照" in answer and "可能随时间变化" in answer
    assert "analysis.md" in answer and "W01" in answer and "P001" in answer


def test_target_gap_renderer_keeps_all_requested_warehouses_and_source_units():
    state = {
        "request_constraints": {"warehouse_ids": ["W01", "W02"], "part_ids": ["P001"],
                                "intent": "target_replenishment"},
        "plan": [PlanItem(id="inventory", title="库存", status="done", query_evidence=[
            {"call_id": "w1", "tool_name": "inventory_page", "data_source": "local_seed",
             "arguments": {"warehouse_id": "W01", "part_ids": ["P001"], "page": 1, "page_size": 20}, "as_of": "2026-10-25T10:00:00Z",
             "total": 1, "page": 1, "pages": 1, "record_ids": ["I001"]},
            {"call_id": "w2", "tool_name": "inventory_page", "data_source": "local_seed",
             "arguments": {"warehouse_id": "W02", "part_ids": ["P001"], "page": 1, "page_size": 20}, "as_of": "2026-10-25T10:00:00Z",
             "total": 1, "page": 1, "pages": 1, "record_ids": ["I002"]},
        ]).model_dump(mode="json")],
        "evidence": [
            {"call_id": "w1", "field": "shortage", "value": 55, "unit": "套", "part_id": "P001", "warehouse_id": "W01"},
            {"call_id": "w2", "field": "shortage", "value": 20, "unit": "箱", "part_id": "P001", "warehouse_id": "W02"},
        ],
    }
    answer = render_verified_core_facts(state)
    assert answer is not None
    assert "W01的P001目标库存缺口为55套" in answer
    assert "W02的P001目标库存缺口为20箱" in answer


def test_complete_empty_warehouse_is_reported_without_inventing_inventory_facts():
    state = {
        "request_constraints": {"warehouse_ids": ["W99"], "part_ids": [], "intent": "target_replenishment"},
        "plan": [PlanItem(id="inventory", title="库存", status="done", query_evidence=[{
            "call_id": "empty", "tool_name": "inventory_page", "data_source": "local_seed",
            "arguments": {"warehouse_id": "W99", "page": 1, "page_size": 20},
            "as_of": "2026-10-25T10:00:00Z", "total": 0, "page": 1, "pages": 1,
            "record_ids": [],
        }]).model_dump(mode="json")],
        "evidence": [],
    }
    answer = render_verified_core_facts(state)
    assert answer is not None
    assert "W99未发现正的目标库存缺口" in answer
    assert "空仓范围：W99未返回库存记录" in answer
