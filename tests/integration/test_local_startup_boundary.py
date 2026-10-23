"""P00-F01：真实 Next→Uvicorn 链路、回环监听与 Host/Origin 边界。

该测试启动真实 Uvicorn 和 Next dev，不使用 TestClient 代替代理链；
临时端口随机，数据库使用 technologyagent_test_ 前缀并在 finally 删除。
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
from pymongo import MongoClient

from tests.integration.conftest import TEST_DB_PREFIX, TEST_MONGODB_URI

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / ".runtime" / "test-logs"


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _non_loopback_ipv4() -> str | None:
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if not address.startswith("127."):
                return address
    except OSError:
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
            if not address.startswith("127."):
                return address
        finally:
            sock.close()
    except OSError:
        return None
    return None


def _wait_http(url: str, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=3.0, trust_env=False)
            if response.status_code == 200:
                return
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
        except Exception as exc:  # noqa: BLE001 - 启动等待要收集任意连接错误
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.5)
    raise AssertionError(f"service did not become ready: {url}; last={last_error}")


def _start_process(argv: list[str], env: dict[str, str], log_path: Path) -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8")
    kwargs: dict[str, object] = {
        "cwd": str(ROOT),
        "env": env,
        "stdout": log,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(argv, **kwargs)
    process._test_log = log  # type: ignore[attr-defined]
    return process


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
            )
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    with contextlib.suppress(Exception):
        process.wait(timeout=10)
    log = getattr(process, "_test_log", None)
    if log is not None:
        log.close()


def _assert_loopback_only(port: int, address: str) -> None:
    with pytest.raises(OSError):
        connection = socket.create_connection((address, port), timeout=1.0)
        connection.close()


def test_real_next_to_uvicorn_boundary_and_session():
    database = f"{TEST_DB_PREFIX}f01_{uuid.uuid4().hex[:10]}"
    assert database.startswith(TEST_DB_PREFIX)
    api_port = _free_port()
    frontend_port = _free_port()
    frontend_base = f"http://127.0.0.1:{frontend_port}"
    api_base = f"http://127.0.0.1:{api_port}"

    env = os.environ.copy()
    env.update(
        {
            "APP_MODE": "local",
            "API_PORT": str(api_port),
            "FRONTEND_PORT": str(frontend_port),
            "MONGODB_URI": TEST_MONGODB_URI,
            "MONGODB_DATABASE": database,
            "LOCAL_SESSION_SECRET": "f01-test-only-secret",
            "MODEL_MODE": "fake",
            "NEXT_TELEMETRY_DISABLED": "1",
        }
    )
    python = sys.executable
    node = shutil.which("node") or "node"
    uvicorn: subprocess.Popen | None = None
    next_dev: subprocess.Popen | None = None
    try:
        uvicorn = _start_process(
            [
                python,
                "-m",
                "uvicorn",
                "backend.app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
                "--no-proxy-headers",
                "--log-level",
                "warning",
            ],
            env,
            LOG_DIR / "f01-uvicorn.log",
        )
        _wait_http(f"{api_base}/health", timeout=60)
        next_dev = _start_process(
            [node, "frontend/scripts/run-next.mjs", "dev"],
            env,
            LOG_DIR / "f01-next.log",
        )
        _wait_http(f"{frontend_base}/health", timeout=120)

        local_address = _non_loopback_ipv4()
        assert local_address, "no non-loopback IPv4 address to verify loopback-only binding"
        _assert_loopback_only(frontend_port, local_address)
        _assert_loopback_only(api_port, local_address)

        # 正常浏览器同源路径：Next 代理、Origin 校验、Strict Cookie、读取身份。
        with httpx.Client(timeout=20.0, trust_env=False) as browser:
            health = browser.get(f"{frontend_base}/health")
            assert health.status_code == 200, health.text
            assert health.json()["data"]["component"] == "api"

            created = browser.post(
                f"{frontend_base}/api/session/local",
                headers={"Origin": f"http://127.0.0.1:{frontend_port}"},
            )
            assert created.status_code == 200, created.text
            cookie = created.headers.get("set-cookie", "")
            assert "HttpOnly" in cookie
            assert "SameSite=strict" in cookie
            assert cookie.strip()

            me = browser.get(f"{frontend_base}/api/session/me")
            assert me.status_code == 200, me.text
            assert me.json()["data"]["owner_id"] == "local-owner"

        # 恶意 Origin + 伪造 XFF，经真实 Next 代理仍不能建立本机会话。
        with httpx.Client(timeout=20.0, trust_env=False) as attacker:
            blocked = attacker.post(
                f"{frontend_base}/api/session/local",
                headers={
                    "Origin": "http://evil.example",
                    "X-Forwarded-For": "127.0.0.1",
                },
            )
        assert blocked.status_code == 403, blocked.text
        assert blocked.json()["error"]["code"] == "LOCAL_SESSION_DISABLED"

        # 直接访问 Uvicorn 时，XFF 不改变真实 peer：--no-proxy-headers 下仍按 127.0.0.1 处理。
        xff_result = httpx.post(
            f"{api_base}/api/session/local",
            headers={
                "Host": f"127.0.0.1:{api_port}",
                "Origin": f"http://127.0.0.1:{frontend_port}",
                "X-Forwarded-For": "198.51.100.25",
            },
            timeout=10.0,
            trust_env=False,
        )
        assert xff_result.status_code == 200, xff_result.text

        # 直接访问 Uvicorn 时，伪造 Host/Origin/XFF 仍不能通过边界。
        blocked_direct = httpx.post(
            f"{api_base}/api/session/local",
            headers={
                "Host": f"192.0.2.10:{api_port}",
                "Origin": f"http://192.0.2.10:{frontend_port}",
                "X-Forwarded-For": "127.0.0.1",
            },
            timeout=10.0,
            trust_env=False,
        )
        assert blocked_direct.status_code == 403, blocked_direct.text
        assert blocked_direct.json()["error"]["code"] == "LOCAL_SESSION_DISABLED"
    finally:
        _stop_process(next_dev)
        _stop_process(uvicorn)
        client = MongoClient(TEST_MONGODB_URI, serverSelectionTimeoutMS=2500)
        try:
            assert database.startswith(TEST_DB_PREFIX)
            client.drop_database(database)
        finally:
            client.close()
