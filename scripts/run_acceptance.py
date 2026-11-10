"""Run P09 acceptance in a named scope and preserve its real verifier report."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from scripts.acceptance_provenance import (
    collect_acceptance_provenance,
    finalize_acceptance_provenance,
)

ROOT = Path(__file__).resolve().parents[1]


def _batch_id() -> str:
    configured = os.environ.get("P09_EVIDENCE_BATCH", "").strip()
    if configured:
        return configured[:80]
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]


def _attach_provenance(report: Path, provenance: dict, exit_code: int) -> None:
    """Add provenance without rewriting the verifier's checks, ok or not_run values."""
    try:
        body = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"provenance not attached to {report}: {exc}")
        return
    if not isinstance(body, dict):
        print(f"provenance not attached to {report}: report is not an object")
        return
    body["batch_id"] = provenance.get("batch_id")
    body["provenance"] = provenance
    body["acceptance_exit_code"] = exit_code
    report.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run isolated P09 acceptance checks")
    parser.add_argument("--scope", choices=("local", "erp"), required=True)
    parser.add_argument("--mode", choices=("offline", "live", "browser"), required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    report = args.report if args.report.is_absolute() else ROOT / args.report
    if report.exists():
        print(f"refusing to overwrite an existing acceptance report: {report}")
        return 3
    report.parent.mkdir(parents=True, exist_ok=True)
    batch_id = _batch_id()
    os.environ["P09_BATCH_ID"] = batch_id
    provenance = collect_acceptance_provenance(ROOT)
    provenance["batch_id"] = batch_id
    if args.scope == "erp":
        body = {
            "stage": "P09", "scope": "erp", "mode": args.mode, "ok": False,
            "not_run": True, "status": "not_run",
            "note": "真实ERP验收需用户指定的ERP测试环境、测试授权及关联号；本地模拟不计入ERP证据。",
            "started_at": datetime.now(timezone.utc).isoformat(), "checks": [],
            "batch_id": batch_id,
        }
        report.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        finalized = finalize_acceptance_provenance(provenance, ROOT)
        _attach_provenance(report, finalized, 2)
        print("P09 ERP: not_run (no explicitly authorized test ERP environment)")
        print(f"report: {report}")
        return 2
    command = [sys.executable, "-m", "scripts.verify_stage", "P09", "--mode", args.mode,
               "--report", str(report)]
    result = subprocess.run(command, cwd=ROOT, check=False)
    finalized = finalize_acceptance_provenance(provenance, ROOT)
    _attach_provenance(report, finalized, result.returncode)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
