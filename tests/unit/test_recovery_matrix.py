from backend.app.services.recovery import classify_recovery


def test_waiting_approval_preserves_checkpoint_without_write_retry():
    result = classify_recovery({"status": "waiting_input", "pending_interrupt": {"kind": "approval"}}, [])
    assert result.action == "preserve_checkpoint"
    assert result.retry_business_write is False


def test_unknown_or_processing_operation_is_reconciled_without_replay():
    unknown = classify_recovery({"status": "running"}, [{"status": "outcome_unknown"}])
    processing = classify_recovery({"status": "running"}, [{"status": "processing"}])
    assert unknown.action == "reconcile_external"
    assert processing.action == "inspect_lease"
    assert not unknown.retry_business_write and not processing.retry_business_write


def test_committed_operation_returns_saved_result_and_checkpoint_is_resumable():
    committed = classify_recovery({"status": "running"}, [{"status": "succeeded"}])
    checkpoint = classify_recovery({"status": "running", "checkpoint_exists": True}, [])
    assert committed.action == "return_committed_result"
    assert checkpoint.action == "resume_checkpoint"
    assert not committed.retry_business_write and not checkpoint.retry_business_write
