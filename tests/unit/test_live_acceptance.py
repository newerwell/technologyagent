from scripts.live_acceptance import validate_live_run


def test_live_acceptance_rejects_fake_or_failed_run_even_when_summary_matches():
    events = [
        {"type": "run_started", "payload": {"model_mode": "fake"}},
        {"type": "tool_started", "payload": {"call_id": "c", "name": "inventory_page", "args_summary": {}}},
        {"type": "tool_finished", "payload": {"call_id": "c", "status": "error", "result_summary": "P001 55"}},
        {"type": "run_finished", "payload": {"status": "failed", "summary": "P001 缺口55"}},
    ]
    passed, reasons = validate_live_run(events, 0)
    assert not passed
    assert len(reasons) >= 4


def test_live_acceptance_requires_correct_arguments_result_and_terminal_event():
    events = [
        {"type": "run_started", "payload": {"model_mode": "live"}},
        {"type": "tool_started", "payload": {"call_id": "c", "name": "inventory_page", "args_summary": {"warehouse_id": "W02"}}},
        {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"records":[{"id":"I001","part_id":"P001","warehouse_id":"W01","shortage":55}]}' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "P001 W01 缺口55"}},
        {"type": "stream_end", "payload": {"reason": "completed"}},
    ]
    passed, reasons = validate_live_run(events, 0)
    assert not passed
    assert any("did not contain" in reason for reason in reasons)


def test_live_acceptance_accepts_complete_fact_matched_readonly_run():
    events = [
        {"type": "run_started", "payload": {"model_mode": "live"}},
        {"type": "tool_started", "payload": {"call_id": "c", "name": "inventory_page", "args_summary": {"warehouse_id": "W01"}}},
            {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"records":[{"id":"I001","part_id":"P001","warehouse_id":"W01","shortage":55,"unit":"件"},{"id":"I003","part_id":"P003","warehouse_id":"W01","shortage":36,"unit":"件"},{"id":"I004","part_id":"P004","warehouse_id":"W01","shortage":10,"unit":"件"}],"total":3,"page":1,"page_size":50,"pages":1}' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "W01目标缺口：P001缺口55件、P003缺口36件、P004缺口10件"}},
        {"type": "stream_end", "payload": {"reason": "completed"}},
    ]
    assert validate_live_run(events, 0) == (True, [])


def test_live_acceptance_accepts_verified_part_code_as_p001_identity():
    events = [
        {"type": "run_started", "payload": {"model_mode": "live"}},
        {"type": "tool_started", "payload": {"call_id": "p", "name": "part_query", "args_summary": {"part_id": "P001"}}},
        {"type": "tool_finished", "payload": {"call_id": "p", "status": "success", "result_summary": '{"id":"P001","code":"BRK-001","name":"刹车片"}'}},
        {"type": "tool_started", "payload": {"call_id": "i", "name": "inventory_page", "args_summary": {"warehouse_id": "W01"}}},
            {"type": "tool_finished", "payload": {"call_id": "i", "status":"success", "result_summary": '{"records":[{"id":"I001","part_id":"P001","warehouse_id":"W01","shortage":55,"unit":"件"},{"id":"I003","part_id":"P003","warehouse_id":"W01","shortage":36,"unit":"件"},{"id":"I004","part_id":"P004","warehouse_id":"W01","shortage":10,"unit":"件"}],"total":3,"page":1,"page_size":50,"pages":1}' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "W01目标缺口：P001（BRK-001）缺口55件、P003缺口36件、P004缺口10件"}},
        {"type": "stream_end", "payload": {"reason": "completed"}},
    ]
    assert validate_live_run(events, 0) == (True, [])


def test_live_acceptance_uses_verified_filter_scope_for_seven_day_question():
    events = [
        {"type": "run_started", "payload": {"model_mode": "live"}},
        {"type": "tool_started", "payload": {"call_id": "c", "name": "replenishment_preview", "args_summary": {"warehouse_id": "W01", "part_ids": ["P001"], "max_lead_days": 7}}},
        {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"lines":[{"part_id":"P001","warehouse_id":"W01","quantity":55,"total_cents":66000,"candidate_quotes":[{"supplier_id":"S01","supplier_name":"新达供应","lead_days":5}]}],"source_refs":[{"entity":"inventory","id":"I001"}]}' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "7天内到货推荐新达供应，交期5天。"}},
        {"type": "stream_end", "payload": {"reason": "completed"}},
    ]
    assert validate_live_run(events, 1) == (True, [])


def test_live_acceptance_rejects_final_answer_that_denies_successful_shortage_fact():
    events = [
        {"type": "run_started", "payload": {"model_mode": "live"}},
        {"type": "tool_started", "payload": {"call_id": "c", "name": "replenishment_preview", "args_summary": {"part_ids": ["P001"], "warehouse_id": "W01"}}},
        {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"lines":[{"part_id":"P001","warehouse_id":"W01","shortage":55,"quantity":55,"total_cents":66000}],"source_refs":[{"entity":"inventory","id":"I001"}]}' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "P001库存充足，无需补货。"}},
        {"type": "stream_end", "payload": {"reason": "completed"}},
    ]
    passed, reasons = validate_live_run(events, 0)
    assert not passed
    assert any("final answer" in reason for reason in reasons)


def test_live_acceptance_rejects_correct_tool_result_with_unrelated_final_text():
    events = [
        {"type": "run_started", "payload": {"model_mode": "live"}},
        {"type": "tool_started", "payload": {"call_id": "c", "name": "inventory_page", "args_summary": {"warehouse_id": "W01"}}},
        {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"records":[{"id":"I001","part_id":"P001","warehouse_id":"W01","shortage":55}]}' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "已核对，结果正常。"}},
        {"type": "stream_end", "payload": {"reason": "completed"}},
    ]
    passed, reasons = validate_live_run(events, 0)
    assert not passed
    assert any("did not answer" in reason for reason in reasons)


def test_live_acceptance_requires_nonempty_quote_evidence_and_a_named_supplier_answer():
    events = [
        {"type": "run_started", "payload": {"model_mode": "live"}},
        {"type": "tool_started", "payload": {"call_id": "c", "name": "quote_list", "args_summary": {"part_id": "P003"}}},
        {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"records":[]}' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "P003没有有效报价。"}},
        {"type": "stream_end", "payload": {"reason": "completed"}},
    ]
    passed, reasons = validate_live_run(events, 2)
    assert not passed
    assert any("did not prove" in reason for reason in reasons)


def test_live_acceptance_rejects_opposite_p003_conclusion():
    events = [
        {"type": "run_started", "payload": {"model_mode": "live"}},
        {"type": "tool_started", "payload": {"call_id": "c", "name": "quote_list", "args_summary": {"part_id": "P003"}}},
        {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"records":[{"id":"Q03","is_valid":false}]}' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "P003没有缺口，报价有效。"}},
        {"type": "stream_end", "payload": {"reason": "completed"}},
    ]
    passed, reasons = validate_live_run(events, 2)
    assert not passed
    assert any("no valid quote" in reason for reason in reasons)


def test_live_acceptance_accepts_no_valid_quote_after_part_description():
    events = [
        {"type": "run_started", "payload": {"model_mode": "live"}},
        {"type": "tool_started", "payload": {"call_id": "c", "name": "quote_list", "args_summary": {"part_id": "P003"}}},
        {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"records":[{"id":"Q06","is_valid":false,"supplier_id":"S03"}],"total":1,"page":1,"page_size":50,"pages":1}' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "P003（火花塞，铱金）没有有效报价。"}},
        {"type": "stream_end", "payload": {"reason": "completed"}},
    ]
    assert validate_live_run(events, 2) == (True, [])


def test_live_acceptance_accepts_scoped_no_valid_quote_claim_in_a_long_answer():
    events = [
        {"type": "run_started", "payload": {"model_mode": "live"}},
        {"type": "tool_started", "payload": {"call_id": "c", "name": "quote_list", "args_summary": {"part_id": "P003"}}},
        {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"records":[{"id":"Q06","is_valid":false}],"total":1,"page":1,"page_size":50,"pages":1}' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "P003（火花塞，铱金）目前只有1条报价记录，但**没有有效报价**：供应商已停用且报价已失效，因此这条记录不作为采购依据。结论是无法判断哪家最便宜。"}},
        {"type": "stream_end", "payload": {"reason": "completed"}},
    ]

    assert validate_live_run(events, 2) == (True, [])


def test_live_acceptance_does_not_confuse_safety_warnings_with_all_target_stock_gaps():
    events = [
        {"type": "run_started", "payload": {"model_mode": "live"}},
        {"type": "tool_started", "payload": {"call_id": "c", "name": "inventory_warning", "args_summary": {"warehouse_id": "W01"}}},
        {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"records":[{"id":"I001","part_id":"P001","warehouse_id":"W01","shortage":55,"warning":true},{"id":"I003","part_id":"P003","warehouse_id":"W01","shortage":36,"warning":true}],"total":2,"page":1,"page_size":50,"pages":1}' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "W01需要补货的零件共2个：P001缺口55件、P003缺口36件。"}},
        {"type": "stream_end", "payload": {"reason": "completed"}},
    ]

    passed, reasons = validate_live_run(events, 0)

    assert not passed
    assert any("P004" in reason or "target" in reason.lower() for reason in reasons)


def test_live_acceptance_rejects_no_valid_quote_followed_by_contradiction_or_bad_recommendation():
    for summary in (
        "P003没有有效报价。P003报价有效。",
        "P003没有有效报价。推荐P003向S03采购。",
    ):
        events = [
            {"type": "run_started", "payload": {"model_mode": "live"}},
            {"type": "tool_started", "payload": {"call_id": "c", "name": "quote_list", "args_summary": {"part_id": "P003"}}},
            {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"records":[{"id":"Q06","is_valid":false,"supplier_id":"S03"}],"total":1,"page":1,"page_size":50,"pages":1}'}},
            {"type": "run_finished", "payload": {"status": "completed", "summary": summary}},
            {"type": "stream_end", "payload": {"reason": "completed"}},
        ]
        passed, reasons = validate_live_run(events, 2)
        assert not passed, reasons


def test_live_acceptance_requires_every_positive_target_gap_in_answer():
    events = [
        {"type": "run_started", "payload": {"model_mode": "live"}},
        {"type": "tool_started", "payload": {"call_id": "c", "name": "inventory_page", "args_summary": {"warehouse_id": "W01"}}},
        {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"records":[{"id":"I001","part_id":"P001","warehouse_id":"W01","shortage":55},{"id":"I003","part_id":"P003","warehouse_id":"W01","shortage":36},{"id":"I004","part_id":"P004","warehouse_id":"W01","shortage":10}],"total":3,"page":1,"page_size":50,"pages":1}' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "W01目标缺口：P001缺口55件、P003缺口36件"}},
        {"type": "stream_end", "payload": {"reason": "completed"}},
    ]

    passed, reasons = validate_live_run(events, 0)

    assert not passed
    assert any("P004" in reason for reason in reasons)


def test_live_acceptance_rejects_unparseable_truncated_success_summary_as_insufficient_evidence():
    events = [
        {"type": "run_started", "payload": {"model_mode": "live"}},
        {"type": "tool_started", "payload": {"call_id": "c", "name": "inventory_page", "args_summary": {"warehouse_id": "W01"}}},
        {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"records":[{"id":"I001"' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "P001/W01缺口55件、P003/W01缺口36件、P004/W01缺口10件"}},
        {"type": "stream_end", "payload": {"reason": "completed"}},
    ]

    passed, reasons = validate_live_run(events, 0)

    assert not passed
    assert any("insufficient evidence" in reason for reason in reasons)


def test_persisted_failed_run_matching_failed_terminal_is_not_reported_as_snapshot_mismatch():
    from scripts.live_acceptance import compare_persisted_terminal

    events = [{"type": "run_finished", "payload": {"status": "failed", "summary": "tool error"}}]

    assert compare_persisted_terminal(events, {"status": "failed", "summary": "tool error"}) == []
    assert compare_persisted_terminal(events, {"status": "completed", "summary": "tool error"})
