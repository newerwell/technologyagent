from __future__ import annotations

import subprocess

import scripts.verify_stage as verify_stage
from scripts.verify_stage import Check, MANIFESTS, PYTHON, run_check


def test_p09_live_manifest_requires_executed_pytest_case():
    assert MANIFESTS["P09"]["live"][0].require_pytest_pass is True


def test_p09_live_gate_rejects_all_skipped_pytest_with_exit_zero(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args[0], 0, stdout="1 skipped in 0.01s", stderr=""))
    result = run_check(Check("final_live_scenarios", (PYTHON, "-m", "pytest", "tests/live"),
                             require_pytest_pass=True))
    assert result["status"] == "failed"


def test_p09_live_gate_rejects_missing_summary_and_partial_skip(monkeypatch):
    outputs = iter(["pytest started", "1 passed, 1 skipped in 0.04s"])
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args[0], 0, stdout=next(outputs), stderr=""))
    for _ in range(2):
        result = run_check(Check("final_live_scenarios", (PYTHON, "-m", "pytest", "tests/live"),
                                 require_pytest_pass=True))
        assert result["status"] == "failed"


def test_live_wrapper_records_timeout_and_never_overwrites(monkeypatch):
    from types import SimpleNamespace
    import shutil
    import uuid
    from pathlib import Path

    from scripts import verify_stage
    from tests.live import test_final_scenarios as wrapper

    root = Path(__file__).resolve().parents[2] / ".runtime" / f"p09-wrapper-test-{uuid.uuid4().hex}"
    monkeypatch.setattr(wrapper, "__file__", str(root / "tests" / "live" / "test_final_scenarios.py"))
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(
        verify_stage.subprocess.TimeoutExpired(args[0], kwargs.get("timeout"), output="started", stderr="timeout")))
    settings = SimpleNamespace(
        mongodb_database="technologyagent_test_wrapper", model_name="test-model", model_api_key=None,
        mongodb_uri=SimpleNamespace(get_secret_value=lambda: "mongodb://unused"),
    )
    monkeypatch.setenv("P09_BATCH_ID", "timeout-batch")

    try:
        first = wrapper._record_attempt("F04-order", "tests/live/test_order_workflow.py", 1, settings)
        second = wrapper._record_attempt("F04-order", "tests/live/test_order_workflow.py", 1, settings)

        assert first["status"] == "failed" and first["started_at"]
        assert second["status"] == "failed"
        assert first["evidence_path"] != second["evidence_path"]
        assert (root / first["evidence_path"]).exists()
        assert (root / second["evidence_path"]).exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_p09_summary_uses_the_exact_attempt_record_paths():
    from tests.live.test_final_scenarios import _summary_record_paths

    results = [
        {"scenario": "F08-review", "attempt": 1, "evidence_path": ".runtime/live/p09/attempts/batch/F08-review-attempt-1-a1.json"},
        {"scenario": "F08-review", "attempt": 2, "evidence_path": ".runtime/live/p09/attempts/batch/F08-review-attempt-2-b2.json"},
    ]
    assert _summary_record_paths(results) == [item["evidence_path"] for item in results]
