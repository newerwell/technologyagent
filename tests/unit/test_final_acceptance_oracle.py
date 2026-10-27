from __future__ import annotations

from scripts.live_acceptance import validate_preference_attempt


def _run_events(*, mode="live", status="completed", review=True, tool_status="success", early=False):
    events = [
        {"type": "run_started", "seq": 1, "run_id": "run-1", "thread_id": "thread-1",
         "payload": {"run_id": "run-1", "thread_id": "thread-1", "model_mode": mode}},
        {"type": "review", "seq": 2, "run_id": "run-1", "payload": {"passed": review,
         "checks": ["PREFERENCE_PERSISTED", "NUMERIC_MATCH", "REQUEST_CONSTRAINTS"],
         "result": {"passed": review, "checks": [
             {"check_id": "PREFERENCE_PERSISTED", "passed": review},
             {"check_id": "NUMERIC_MATCH", "passed": review},
             {"check_id": "REQUEST_CONSTRAINTS", "passed": review},
         ]}}},
        {"type": "plan", "seq": 3, "run_id": "run-1", "payload": {"request_constraints": {"warehouse_ids": ["W01"]}}},
        {"type": "tool_started", "seq": 4, "run_id": "run-1", "payload": {
            "call_id": "call-1", "name": "inventory_page", "args_summary": {"warehouse_id": "W01"}}},
        {"type": "tool_finished", "seq": 5, "run_id": "run-1", "payload": {
            "call_id": "call-1", "status": tool_status, "source": "local_seed",
            "result_summary": '{"records":[{"part_id":"P001","warehouse_id":"W01","shortage":55,"unit":"套"}]}' }},
        {"type": "run_finished", "seq": 6, "run_id": "run-1", "payload": {
            "status": status, "review_passed": review, "summary": "P001在W01的目标库存缺口为55套。"}},
    ]
    if not early:
        events.append({"type": "stream_end", "seq": 7, "run_id": "run-1",
                       "payload": {"reason": status, "last_seq": 7}})
    return events


def _valid_attempt():
    return {
        "remember_events": _run_events(),
        "query_events": _run_events(),
        "remember_run": {"status": "completed", "review": {"passed": True}},
        "query_run": {"status": "completed", "review": {"passed": True}},
        "remember_preferences": {"default_warehouse": "W01"},
        "query_preferences": {"default_warehouse": "W01"},
        "database_before": {"orders": 2, "inventory": {"I001": {"on_hand": 20, "inbound": 10}}},
        "database_after": {"orders": 2, "inventory": {"I001": {"on_hand": 20, "inbound": 10}}},
        "answer": "P001在W01还需要补货55套。",
    }


def test_preference_acceptance_requires_two_completed_live_runs_and_fact_proof():
    assert validate_preference_attempt(_valid_attempt()) == []


def test_preference_save_requires_persisted_pass_review_and_terminal_completion():
    attempt = _valid_attempt()
    attempt["remember_events"][1]["payload"]["passed"] = False
    attempt["remember_events"][1]["payload"]["result"]["passed"] = False
    attempt["remember_events"][5]["payload"]["review_passed"] = False
    attempt["remember_run"]["review"]["passed"] = False
    issues = validate_preference_attempt(attempt)
    assert any("remember_events" in issue for issue in issues)
    assert any("remember_run" in issue for issue in issues)


def test_preference_followup_requires_default_warehouse_in_query_constraints():
    attempt = _valid_attempt()
    attempt["query_events"][2]["payload"]["request_constraints"] = {"warehouse_ids": ["W02"]}
    assert any("request constraints" in issue for issue in validate_preference_attempt(attempt))


def test_preference_followup_review_must_link_shortage_answer_to_numeric_and_scope_evidence():
    attempt = _valid_attempt()
    attempt["query_events"][1]["payload"]["checks"] = ["SOURCE_EXISTS"]
    attempt["query_events"][1]["payload"]["result"]["checks"] = [
        {"check_id": "NUMERIC_MATCH", "passed": False},
        {"check_id": "REQUEST_CONSTRAINTS", "passed": False},
    ]
    attempt["query_events"][1]["payload"]["result"]["checks"] = [
        {"check_id": "NUMERIC_MATCH", "passed": False},
        {"check_id": "REQUEST_CONSTRAINTS", "passed": False},
    ]
    assert any("numeric and request-scope" in issue for issue in validate_preference_attempt(attempt))


def test_preference_acceptance_rejects_failed_remember_even_when_query_looks_valid():
    attempt = _valid_attempt()
    attempt["remember_events"] = _run_events(status="failed", review=False)
    assert validate_preference_attempt(attempt)


def test_preference_acceptance_rejects_fake_run_and_failed_tool_after_w01_request():
    attempt = _valid_attempt()
    attempt["query_events"] = _run_events(mode="fake")
    assert validate_preference_attempt(attempt)
    attempt = _valid_attempt()
    attempt["query_events"] = _run_events(tool_status="error")
    assert validate_preference_attempt(attempt)


def test_preference_acceptance_rejects_failed_review_early_eof_and_unpersisted_preference():
    attempt = _valid_attempt()
    attempt["query_events"] = _run_events(review=False)
    assert validate_preference_attempt(attempt)
    attempt = _valid_attempt()
    attempt["query_events"] = _run_events(early=True)
    assert validate_preference_attempt(attempt)
    attempt = _valid_attempt()
    attempt["query_preferences"] = {}
    assert validate_preference_attempt(attempt)


def test_preference_acceptance_rejects_wrong_scope_or_changed_business_facts():
    attempt = _valid_attempt()
    attempt["query_events"][3]["payload"]["args_summary"]["warehouse_id"] = "W02"
    assert validate_preference_attempt(attempt)
    attempt = _valid_attempt()
    attempt["database_after"]["orders"] = 3
    assert validate_preference_attempt(attempt)
