"""按阶段 manifest 运行真实检查命令，保存退出码与输出尾部。

用法：
  uv run python -m scripts.verify_stage P00 --mode offline
  uv run python -m scripts.verify_stage P00 --mode offline --report .runtime/reports/P00-offline.json
  uv run python -m scripts.verify_stage P00 --list

规则：退出码 0 才算通过；pytest 退出码 5（没有收集到测试）视为失败，
live/browser 在 P00 没有检查时明确标记 not_run 并返回 2，不能伪装成通过。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / ".runtime" / "reports"

PYTHON = sys.executable


def _find_npm() -> str:
    found = shutil.which("npm")
    if found:
        return found
    return "npm.cmd" if os.name == "nt" else "npm"


NPM = _find_npm()


@dataclass(frozen=True)
class Check:
    name: str
    argv: tuple[str, ...]
    timeout_seconds: int = 600
    required: bool = True

    @property
    def cwd(self) -> Path:
        return ROOT


P00_OFFLINE = (
    Check("db_init", (PYTHON, "-m", "scripts.init_db"), timeout_seconds=180),
    Check("compatibility", (PYTHON, "-m", "scripts.check_compatibility"), timeout_seconds=300),
    Check(
        "integration_tests",
        (PYTHON, "-m", "pytest", "tests/integration", "-q"),
        timeout_seconds=600,
    ),
    Check(
        "frontend_typecheck",
        (NPM, "--prefix", "frontend", "run", "typecheck"),
        timeout_seconds=300,
    ),
    Check(
        "frontend_tests",
        (NPM, "--prefix", "frontend", "run", "test", "--", "--run"),
        timeout_seconds=300,
    ),
    Check(
        "frontend_build",
        (NPM, "--prefix", "frontend", "run", "build"),
        timeout_seconds=600,
    ),
)

MANIFESTS: dict[str, dict[str, tuple[Check, ...]]] = {
    "P00": {
        "offline": P00_OFFLINE,
        "live": (),
        "browser": (),
    }
}

# P00 没有 tests/unit；pytest 对空的 tests/unit 会返回 5，必须判失败。
P00_NOTES = (
    "P00 无 tests/unit，因此 manifest 不含 unit 命令；"
    "P01 起新增的 unit 测试必须成为必跑项。"
)


def classify_exit(exit_code: int, argv: tuple[str, ...]) -> tuple[str, str]:
    is_pytest = any("pytest" in part for part in argv)
    if exit_code == 5 and is_pytest:
        return "failed", "pytest returned exit 5: no tests collected (never treated as success)"
    if exit_code == 0:
        return "passed", ""
    return "failed", f"command exited with {exit_code}"


def _tail(text: str, limit: int = 6000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def run_check(check: Check) -> dict[str, object]:
    started = time.perf_counter()
    exit_code: int | None = None
    status = "failed"
    detail = ""
    stdout = ""
    stderr = ""
    cmd = list(check.argv)
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(check.cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=check.timeout_seconds,
            env=os.environ.copy(),
        )
        exit_code = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        status, detail = classify_exit(exit_code, check.argv)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        status = "failed"
        detail = f"timed out after {check.timeout_seconds}s"
    except FileNotFoundError as exc:
        status = "failed"
        detail = f"executable not found: {exc.filename}"
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        detail = f"{type(exc).__name__}: {exc}"

    output = stdout
    if stderr:
        output += "\n[stderr]\n" + stderr
    return {
        "name": check.name,
        "command": cmd,
        "cwd": str(check.cwd),
        "required": check.required,
        "exit_code": exit_code,
        "status": status,
        "detail": detail,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "output_tail": _tail(output.strip()),
    }


def manifest_as_dict(stage: str, mode: str) -> dict[str, object]:
    checks = MANIFESTS[stage][mode]
    return {
        "stage": stage,
        "mode": mode,
        "checks": [
            {
                "name": check.name,
                "argv": list(check.argv),
                "cwd": str(check.cwd),
                "timeout_seconds": check.timeout_seconds,
                "required": check.required,
            }
            for check in checks
        ],
    }


def _write_report(report: dict[str, object], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按阶段运行真实检查并保存报告")
    parser.add_argument("stage", choices=sorted(MANIFESTS.keys()))
    parser.add_argument("--mode", choices=("offline", "live", "browser"), default="offline")
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--list", action="store_true", help="只打印 manifest，不执行")
    args = parser.parse_args(argv)

    if args.list:
        print(json.dumps(manifest_as_dict(args.stage, args.mode), ensure_ascii=False, indent=2))
        return 0

    report_path = args.report or (REPORT_ROOT / f"{args.stage}-{args.mode}.json")
    if not report_path.is_absolute():
        report_path = ROOT / report_path

    checks = MANIFESTS[args.stage][args.mode]
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()

    if not checks:
        report = {
            "stage": args.stage,
            "mode": args.mode,
            "ok": False,
            "not_run": True,
            "note": f"{args.stage} has no {args.mode} checks; no verification was performed.",
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": 0,
            "checks": [],
        }
        _write_report(report, report_path)
        print(f"{args.stage} {args.mode}: not_run (no checks for this stage/mode)")
        print(f"report: {report_path}")
        return 2

    results: list[dict[str, object]] = []
    for check in checks:
        print(f"==> {check.name}: {' '.join(check.argv)}")
        result = run_check(check)
        results.append(result)
        print(f"    {result['status']} (exit={result['exit_code']}) {result['detail']}")
        if result["status"] != "passed":
            print(result["output_tail"])
        if result["status"] != "passed" and check.required:
            # 继续收集？阶段检查失败即失败，但保留后续命令的实际退出码。
            pass

    passed = all(item["status"] == "passed" for item in results)
    finished_at = datetime.now(timezone.utc)
    report = {
        "stage": args.stage,
        "mode": args.mode,
        "ok": passed,
        "not_run": False,
        "note": P00_NOTES if args.stage == "P00" else "",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "checks": results,
    }
    _write_report(report, report_path)
    print(f"{args.stage} {args.mode}: {'PASS' if passed else 'FAIL'}")
    print(f"report: {report_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
