"""P00-F02：启动脚本按当前 API_PORT 构建，并校验同源 health/ready。"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NPM = shutil.which("npm") or ("npm.cmd" if os.name == "nt" else "npm")


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _build_with_api_port(port: int) -> dict[str, object]:
    env = os.environ.copy()
    env["API_PORT"] = str(port)
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    completed = subprocess.run(
        [NPM, "--prefix", "frontend", "run", "build"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    assert completed.returncode == 0, completed.stdout[-2000:] + "\n" + completed.stderr[-2000:]
    manifest = json.loads(
        (ROOT / "frontend" / ".next" / "routes-manifest.json").read_text(encoding="utf-8")
    )
    return manifest


def test_start_script_binds_loopback_disables_proxy_headers_and_waits_proxied_probes():
    text = (ROOT / "start.ps1").read_text(encoding="utf-8")
    assert '"--host", "127.0.0.1"' in text
    assert '"--no-proxy-headers"' in text
    assert '"start", "-H", "127.0.0.1"' in text
    assert "run build" in text
    assert "BUILD_ID" not in text, "start must not reuse an old .next based on BUILD_ID"
    assert "Wait-FrontendStack" in text
    assert "frontend-build.json" in text
    assert "缺少 --no-proxy-headers" in text
    assert "缺少 127.0.0.1 监听参数" in text


def test_run_next_binds_loopback_for_dev_and_start():
    text = (ROOT / "frontend" / "scripts" / "run-next.mjs").read_text(encoding="utf-8")
    assert 'command, "-H", "127.0.0.1", "-p", port' in text


def test_production_build_rewrites_follow_current_api_port():
    # 用 A/B 两次构建证明 routes-manifest 会随当前 API_PORT 更新，
    # 而不是复用旧的 8030 目标。
    port_a = _free_port()
    port_b = _free_port()
    while port_b == port_a:
        port_b = _free_port()

    try:
        manifest_a = _build_with_api_port(port_a)
        routes_a = {
            item["source"]: item["destination"]
            for item in manifest_a["rewrites"]["afterFiles"]
        }
        assert routes_a["/health"] == f"http://127.0.0.1:{port_a}/health"
        assert routes_a["/ready"] == f"http://127.0.0.1:{port_a}/ready"
        assert routes_a["/api/:path*"] == f"http://127.0.0.1:{port_a}/api/:path*"

        manifest_b = _build_with_api_port(port_b)
        routes_b = {
            item["source"]: item["destination"]
            for item in manifest_b["rewrites"]["afterFiles"]
        }
        assert routes_b["/health"] == f"http://127.0.0.1:{port_b}/health"
        assert routes_b["/ready"] == f"http://127.0.0.1:{port_b}/ready"
        assert routes_b["/api/:path*"] == f"http://127.0.0.1:{port_b}/api/:path*"
    finally:
        # 测试结束后恢复默认构建，避免把随机测试端口留在工作区 .next。
        with contextlib.suppress(Exception):
            _build_with_api_port(8030)
