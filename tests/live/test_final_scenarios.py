"""P09 representative real-model attempts; each subprocess result is retained."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.app.config import load_settings


def _record_attempt(name: str, test_path: str, attempt: int, settings) -> dict:
    root = Path(__file__).resolve().parents[2]
    base = root / ".runtime" / "live" / "p09"
    base.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"RUN_LIVE_MODEL": "1", "MODEL_MODE": "live",
                "MONGODB_DATABASE": settings.mongodb_database,
                "P09_ATTEMPT_LABEL": f"{name}-attempt-{attempt}"})
    seeded = subprocess.run([sys.executable, "-m", "scripts.seed", "--reset"], cwd=root,
                            env=env, text=True, capture_output=True, timeout=300)
    tested = None
    if seeded.returncode == 0:
        if name.startswith("F04-order"):
            # P09-F12 intentionally stores W01; isolate the missing-field
            # workflow from that prior preference before each P04 live trial.
            from pymongo import MongoClient
            client = MongoClient(settings.mongodb_uri.get_secret_value())
            try:
                client[settings.mongodb_database]["preferences"].delete_many({"key": "default_warehouse"})
            finally:
                client.close()
        tested = subprocess.run([sys.executable, "-m", "pytest", test_path, "-q", "-rs"], cwd=root,
                                env=env, text=True, capture_output=True, timeout=1800)
    secret = settings.model_api_key.get_secret_value() if settings.model_api_key else ""
    stdout = (seeded.stdout or "") + (tested.stdout if tested else "")
    stderr = (seeded.stderr or "") + (tested.stderr if tested else "")
    if secret:
        stdout = stdout.replace(secret, "[redacted]")
        stderr = stderr.replace(secret, "[redacted]")
    record = {
        "scenario": name, "attempt": attempt, "model_mode": "live", "model_name": settings.model_name,
        "database": settings.mongodb_database, "started_at": datetime.now(timezone.utc).isoformat(),
        "seed_exit_code": seeded.returncode,
        "test_exit_code": tested.returncode if tested is not None else None,
        "stdout": stdout[-20000:], "stderr": stderr[-10000:],
        "passed": seeded.returncode == 0 and tested is not None and tested.returncode == 0,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    path = base / f"{name}-attempt-{attempt}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def test_final_acceptance_live_attempts_are_preserved():
    settings = load_settings()
    assert os.environ.get("RUN_LIVE_MODEL") == "1"
    assert settings.model_mode == "live" and settings.model_configured
    assert settings.mongodb_database.startswith("technologyagent_test_")

    # P03-A06 itself makes three attempts for each fixed query, covering F02/F03.
    cases = [("F02-F03", "tests/live/test_readonly_agent.py", 1)]
    for attempt in range(1, 4):
        cases.extend([
            ("F04-order", "tests/live/test_order_workflow.py", attempt),
            ("F08-review", "tests/live/test_order_revision_a04.py", attempt),
            ("F11-specialists", "tests/live/test_specialist_flow.py", attempt),
            ("F12-preferences", "tests/live/test_final_preferences.py", attempt),
        ])
    results = [_record_attempt(name, path, attempt, settings) for name, path, attempt in cases]
    summary = {
        "stage": "P09", "model_mode": "live", "model_name": settings.model_name,
        "database": settings.mongodb_database, "attempt_count": len(results),
        "passed": sum(item["passed"] for item in results), "failed": [
            {"scenario": item["scenario"], "attempt": item["attempt"],
             "seed_exit_code": item["seed_exit_code"], "test_exit_code": item["test_exit_code"]}
            for item in results if not item["passed"]],
        "records": [f"{item['scenario']}-attempt-{item['attempt']}.json" for item in results],
    }
    report = Path(".runtime/live/p09/summary.json")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert all(item["passed"] for item in results), f"P09 live had failures; see {report}"
