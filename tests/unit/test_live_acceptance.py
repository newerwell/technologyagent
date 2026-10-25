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
        {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"records":[{"id":"I001","part_id":"P001","warehouse_id":"W01","shortage":55}]}' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "P001 在 W01 缺口55"}},
        {"type": "stream_end", "payload": {"reason": "completed"}},
    ]
    assert validate_live_run(events, 0) == (True, [])


def test_live_acceptance_accepts_verified_part_code_as_p001_identity():
    events = [
        {"type": "run_started", "payload": {"model_mode": "live"}},
        {"type": "tool_started", "payload": {"call_id": "p", "name": "part_query", "args_summary": {"part_id": "P001"}}},
        {"type": "tool_finished", "payload": {"call_id": "p", "status": "success", "result_summary": '{"id":"P001","code":"BRK-001","name":"刹车片"}'}},
        {"type": "tool_started", "payload": {"call_id": "i", "name": "inventory_page", "args_summary": {"warehouse_id": "W01"}}},
        {"type": "tool_finished", "payload": {"call_id": "i", "status": "success", "result_summary": '{"records":[{"id":"I001","part_id":"P001","warehouse_id":"W01","shortage":55}]}' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "BRK-001 在 W01 缺口55"}},
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
        {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"records":[{"id":"Q06","is_valid":false,"supplier_id":"S03"}]}' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "P003（火花塞，铱金）没有有效报价。"}},
        {"type": "stream_end", "payload": {"reason": "completed"}},
    ]
    assert validate_live_run(events, 2) == (True, [])
