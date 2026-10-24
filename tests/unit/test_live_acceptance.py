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
        {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"records":[{"part_id":"P001","warehouse_id":"W01","shortage":55}]}' }},
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
        {"type": "tool_finished", "payload": {"call_id": "c", "status": "success", "result_summary": '{"records":[{"part_id":"P001","warehouse_id":"W01","shortage":55}]}' }},
        {"type": "run_finished", "payload": {"status": "completed", "summary": "P001 在 W01 缺口55"}},
        {"type": "stream_end", "payload": {"reason": "completed"}},
    ]
    assert validate_live_run(events, 0) == (True, [])
