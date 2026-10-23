"""FastAPI 依赖：服务注入、请求 ID 与本地会话身份。"""

from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import Depends, Request

from backend.app.bootstrap import Container
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


async def get_context(
    request: Request,
    container: Container = Depends(get_container),
) -> RequestContext:
    """从服务端 Cookie 解析身份；请求体中的 user_id/owner_id 不参与。"""
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
