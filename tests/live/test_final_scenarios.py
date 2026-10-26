"""P09 representative real-model attempts; each subprocess result is retained."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.app.config import load_settings
from scripts.live_acceptance import pytest_execution_issues


def _record_attempt(name: str, test_path: str, attempt: int, settings) -> dict:
    root = Path(__file__).resolve().parents[2]
    base = root / ".runtime" / "live" / "p09"
    base.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"RUN_LIVE_MODEL": "1", "MODEL_MODE": "live",
                "MONGODB_DATABASE": settings.mongodb_database,
                "P09_ATTEMPT_LABEL": f"{name}-attempt-{attempt}"})
    batch_id = re.sub(r"[^A-Za-z0-9_-]", "", os.environ.get("P09_BATCH_ID", ""))[:80]
    if not batch_id:
        batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "", name)[:80] or "scenario"
    attempt_id = uuid.uuid4().hex[:12]
    path = base / "attempts" / batch_id / f"{safe_name}-attempt-{attempt}-{attempt_id}.json"
    secret = settings.model_api_key.get_secret_value() if settings.model_api_key else ""
    record = {
        "scenario": name, "attempt": attempt, "model_mode": "live", "model_name": settings.model_name,
        "database": settings.mongodb_database, "batch_id": batch_id, "attempt_id": attempt_id,
        "started_at": datetime.now(timezone.utc).isoformat(), "status": "running", "passed": False,
        "seed_exit_code": None, "test_exit_code": None, "seed_status": "not_run", "test_status": "not_run",
        "stdout": "", "stderr": "", "issues": [], "evidence_path": str(path.relative_to(root)),
    }

    def save() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        payload = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
        if secret:
            payload = payload.replace(secret, "[redacted]")
        temp.write_text(payload, encoding="utf-8")
        temp.replace(path)

    def execute(label: str, command: list[str], timeout: int):
        try:
            result = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True, timeout=timeout)
            record[f"{label}_exit_code"] = result.returncode
            record[f"{label}_status"] = "passed" if result.returncode == 0 else "failed"
            record["stdout"] += (result.stdout or "")
            record["stderr"] += (result.stderr or "")
            return result
        except subprocess.TimeoutExpired as exc:
            record[f"{label}_status"] = "timeout"
            record["issues"].append(f"{label} timed out after {timeout}s")
            for key, value in (("stdout", exc.stdout), ("stderr", exc.stderr)):
                if value:
                    decoded = value.decode(errors="replace") if isinstance(value, bytes) else str(value)
                    record[key] += decoded
            return None
        except Exception as exc:
            record[f"{label}_status"] = "error"
            record["issues"].append(f"{label} raised {type(exc).__name__}: {str(exc)[:500]}")
            return None
        finally:
            save()

    try:
        save()
        seeded = execute("seed", [sys.executable, "-m", "scripts.seed", "--reset"], 300)
        if seeded is not None and seeded.returncode == 0:
            if name.startswith("F04-order"):
                from pymongo import MongoClient
                client = MongoClient(settings.mongodb_uri.get_secret_value())
                try:
                    client[settings.mongodb_database]["preferences"].delete_many({"key": "default_warehouse"})
                finally:
                    client.close()
            tested = execute("test", [sys.executable, "-m", "pytest", test_path, "-q", "-rs"], 1800)
            if tested is not None:
                pytest_issues = pytest_execution_issues((tested.stdout or "") + "\n" + (tested.stderr or ""))
                record["issues"].extend(pytest_issues)
        else:
            record["issues"].append("seed did not complete successfully; live test was not run")
    except Exception as exc:
        record["issues"].append(f"wrapper raised {type(exc).__name__}: {str(exc)[:500]}")
    finally:
        if secret:
            record["stdout"] = record["stdout"].replace(secret, "[redacted]")
            record["stderr"] = record["stderr"].replace(secret, "[redacted]")
        record["stdout"] = record["stdout"][-20000:]
        record["stderr"] = record["stderr"][-10000:]
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        record["passed"] = (record["seed_status"] == "passed" and record["test_status"] == "passed"
                            and not record["issues"])
        record["status"] = "passed" if record["passed"] else "failed"
        save()
    return record


def test_final_acceptance_live_attempts_are_preserved():
    settings = load_settings()
    assert os.environ.get("RUN_LIVE_MODEL") == "1"
    assert settings.model_mode == "live" and settings.model_configured
    assert settings.mongodb_database.startswith("technologyagent_test_")

    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]
    os.environ["P09_BATCH_ID"] = batch_id

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
    report = Path(f".runtime/live/p09/attempts/{batch_id}/summary.json")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert all(item["passed"] for item in results), f"P09 live had failures; see {report}"
