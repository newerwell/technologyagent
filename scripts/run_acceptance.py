"""Run P09 acceptance in a named scope and preserve its real verifier report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run isolated P09 acceptance checks")
    parser.add_argument("--scope", choices=("local", "erp"), required=True)
    parser.add_argument("--mode", choices=("offline", "live", "browser"), required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    report = args.report if args.report.is_absolute() else ROOT / args.report
    report.parent.mkdir(parents=True, exist_ok=True)
    if args.scope == "erp":
        body = {
            "stage": "P09", "scope": "erp", "mode": args.mode, "ok": False,
            "not_run": True, "status": "not_run",
            "note": "真实ERP验收需用户指定的ERP测试环境、测试授权及关联号；本地模拟不计入ERP证据。",
            "started_at": datetime.now(timezone.utc).isoformat(), "checks": [],
        }
        report.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("P09 ERP: not_run (no explicitly authorized test ERP environment)")
        print(f"report: {report}")
        return 2
    command = [sys.executable, "-m", "scripts.verify_stage", "P09", "--mode", args.mode,
               "--report", str(report)]
    result = subprocess.run(command, cwd=ROOT, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
