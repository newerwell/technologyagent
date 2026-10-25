from backend.app.agent.request_intent import parse_request_intent


def test_prepare_order_without_analysis_is_not_split_into_empty_analyst_task():
    intent = parse_request_intent("准备 P001 在 W01 的订单，7天内到货。")
    assert intent.order_prepare is True
    assert intent.analysis_tasks == ()
    assert intent.order_query is False
    assert intent.part_ids == ("P001",)


def test_order_query_and_scoped_negation_do_not_authorize_prepare():
    for message in ("查询已经提交订单的状态", "分析P001库存，不用下单", "我不想下单", "暂时不下单"):
        intent = parse_request_intent(message)
        assert intent.order_prepare is False
    assert parse_request_intent("查询已经提交订单的状态").order_query is True


def test_explicit_chat_memory_commands_are_separate_from_this_turn_override():
    remember = parse_request_intent("记住默认仓库W02")
    override = parse_request_intent("本轮使用W02查询P001库存")
    forget = parse_request_intent("不要记住默认仓库W02")
    assert remember.preference_action == "remember"
    assert remember.preference_values == {"default_warehouse": "W02"}
    assert override.preference_action is None
    assert override.constraints["warehouse_ids"] == ["W02"]
    assert forget.preference_action is None


def test_explicit_supplier_value_and_clear_are_distinguished_from_missing():
    assert parse_request_intent("本轮只用S02，不用S01准备P001订单").constraints["supplier_id"] == "S02"
    cleared = parse_request_intent("本轮不用偏好供应商，也不限交期")
    assert cleared.constraints["supplier_id"] is None
    assert cleared.constraints["clear_preferred_supplier"] is True
    assert cleared.constraints["clear_max_lead_days"] is True
