"""FastAPI 依赖：服务注入、请求 ID 与本地会话身份。"""

from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import Depends, Request

from backend.app.bootstrap import Container
from backend.app.config import Settings
from backend.app.contracts.common import (
    AppError,
    ErrorCodes,
    Envelope,
    Meta,
    RequestContext,
)
from backend.app.services.sessions import SESSION_COOKIE


def get_container(request: Request) -> Container:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise AppError(
            ErrorCodes.DEPENDENCY_UNAVAILABLE,
            "application container is not started",
            http_status=503,
        )
    return container


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def build_meta(
    request: Request,
    container: Container,
    *,
    scope: str | None = None,
    data_source: str = "none",
) -> Meta:
    return Meta(
        request_id=request_id_of(request),
        data_source=data_source,
        as_of=container.clock.now(),
        scope=scope or getattr(request.state, "scope", "anonymous"),
    )


def envelope(
    data: Any,
    request: Request,
    container: Container,
    *,
    scope: str | None = None,
    data_source: str = "none",
) -> Envelope[Any]:
    return Envelope[Any](
        ok=True,
        data=data,
        error=None,
        meta=build_meta(request, container, scope=scope, data_source=data_source),
    )


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def allowed_host_headers(settings: Settings) -> set[str]:
    """本机入口允许的 Host。

    Next 的 rewrite 可能保留前端 Host，也可能改写为后端目标 Host；
    两个配置端口都允许，但不接受局域网 IP 或其他域名。
    """
    hosts: set[str] = set()
    for port in {settings.api_port, settings.frontend_port}:
        hosts.update(
            {
                f"127.0.0.1:{port}",
                f"localhost:{port}",
                f"[::1]:{port}",
            }
        )
    return hosts


def allowed_browser_origins(settings: Settings) -> set[str]:
    """浏览器同源请求允许的 Origin；直接本机脚本不带 Origin。"""
    port = settings.frontend_port
    return {
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
        f"http://[::1]:{port}",
    }


def assert_local_request_boundary(request: Request, settings: Settings) -> None:
    """只允许本机回环 peer、配置内 Host 和同源浏览器 Origin。

    Uvicorn 以 --no-proxy-headers 启动，因此 request.client 是真实 socket peer，
    不采信客户端提供的 X-Forwarded-For/Host。
    """
    if settings.app_mode != "local":
        raise AppError(
            ErrorCodes.LOCAL_SESSION_DISABLED,
            "local development sessions are only available when APP_MODE=local",
            http_status=403,
        )
    client_host = request.client.host if request.client else None
    if not is_loopback_host(client_host):
        raise AppError(
            ErrorCodes.LOCAL_SESSION_DISABLED,
            "local development sessions are only available from loopback",
            http_status=403,
        )
    host = (request.headers.get("host") or "").strip().lower()
    if host not in allowed_host_headers(settings):
        raise AppError(
            ErrorCodes.LOCAL_SESSION_DISABLED,
            "request Host is not an allowed local address",
            http_status=403,
        )
    origin = request.headers.get("origin")
    if origin is not None:
        normalized = origin.strip().lower().rstrip("/")
        if normalized not in allowed_browser_origins(settings):
            raise AppError(
                ErrorCodes.LOCAL_SESSION_DISABLED,
                "cross-origin local session requests are not allowed",
                http_status=403,
            )


async def get_context(
    request: Request,
    container: Container = Depends(get_container),
) -> RequestContext:
    """从服务端 Cookie 解析身份；请求体中的 user_id/owner_id 不参与。"""
    assert_local_request_boundary(request, container.settings)
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        raise AppError(
            ErrorCodes.UNAUTHENTICATED,
            "local session cookie is required",
            http_status=401,
        )
    try:
        record = await container.sessions.resolve(raw_token)
    except Exception as exc:  # noqa: BLE001
        raise AppError(
            ErrorCodes.DEPENDENCY_UNAVAILABLE,
            "session store is unavailable",
            http_status=503,
            retryable=True,
        ) from exc
    if record is None:
        raise AppError(
            ErrorCodes.UNAUTHENTICATED,
            "local session is invalid or expired",
            http_status=401,
        )
    request.state.scope = record.owner_id
    return RequestContext(owner_id=record.owner_id, request_id=request_id_of(request))
