"""stop.ps1 身份校验：CIM 不可用时仍按 PID + 精确启动时间识别登记进程。

真实环境（Next.js 前端）中，子 shell 可能读不到 CommandLine；本用例在 pwsh 里
把 Get-CimInstance 覆盖为空，验证 stop.ps1 仍能结束登记进程。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".runtime" / "processes.json"


def _pwsh(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )


def _start_ticks(pid: int) -> int:
    result = _pwsh(f"$p = Get-Process -Id {pid}; $p.StartTime.ToUniversalTime().Ticks")
    assert result.returncode == 0, result.stderr
    return int(result.stdout.strip())


@pytest.mark.skipif(not STATE.parent.exists(), reason="workspace runtime directory is required")
def test_stop_ps1_kills_recorded_process_without_cim_command_line():
    original = STATE.read_text(encoding="utf-8") if STATE.exists() else None
    dummy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        time.sleep(0.5)
        ticks = _start_ticks(dummy.pid)
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({
            "project_root": str(ROOT),
            "updated_at": "2026-11-10T00:00:00+00:00",
            "processes": [{
                "name": "probe", "pid": dummy.pid, "started_at": "2026-11-10T00:00:00+00:00",
                "start_ticks": ticks, "command": "python -c sleep",
                "markers": ["python"], "port": 0, "logs": [],
            }],
        }), encoding="utf-8")

        result = _pwsh("function global:Get-CimInstance { return $null }; & './stop.ps1'")

        assert result.returncode == 0, result.stderr
        dummy.wait(timeout=10)
        assert dummy.poll() is not None
        assert not STATE.exists()
    finally:
        if dummy.poll() is None:
            dummy.kill()
        if original is None:
            STATE.unlink(missing_ok=True)
        else:
            STATE.write_text(original, encoding="utf-8")
