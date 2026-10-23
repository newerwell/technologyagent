"""localhost 开发会话接口。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict

from backend.app.api.dependencies import (
    envelope,
    get_container,
    get_context,
    is_loopback_host,
)
from backend.app.bootstrap import Container
from backend.app.contracts.common import (
    AppError,
    Envelope,
    ErrorCodes,
    RequestContext,
)
from backend.app.services.sessions import SESSION_COOKIE

router = APIRouter(prefix="/api/session", tags=["session"])


class LocalSessionRequest(BaseModel):
    """owner_id 仅为兼容前端误传而接受，服务端会忽略它。"""

    model_config = ConfigDict(extra="allow")

    owner_id: str | None = None


class SessionData(BaseModel):
    owner_id: str
    mode: str
    created_at: datetime
    expires_at: datetime
    expires_in_seconds: int
    cookie_name: str


class WhoAmIData(BaseModel):
    owner_id: str
    request_id: str
    mode: str


@router.post("/local", response_model=Envelope[SessionData])
async def create_local_session(
    request: Request,
    response: Response,
    body: LocalSessionRequest | None = None,
    container: Container = Depends(get_container),
) -> Envelope[SessionData]:
    # 明确不接受请求体身份；body 仅用于让旧客户端传参时不报错。
    _ = body
    if container.settings.app_mode != "local":
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

    try:
        record, raw_token = await container.sessions.create_local()
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001 - DB 暂不可用时给出可重试错误
        raise AppError(
            ErrorCodes.DEPENDENCY_UNAVAILABLE,
            "session store is unavailable",
            http_status=503,
            retryable=True,
        ) from exc
    response.set_cookie(
        key=SESSION_COOKIE,
        value=raw_token,
        max_age=container.sessions.ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    request.state.scope = record.owner_id
    data = SessionData(
        owner_id=record.owner_id,
        mode="local",
        created_at=record.created_at,
        expires_at=record.expires_at,
        expires_in_seconds=container.sessions.ttl_seconds,
        cookie_name=SESSION_COOKIE,
    )
    return envelope(data, request, container, scope=record.owner_id)


@router.get("/me", response_model=Envelope[WhoAmIData])
async def who_am_i(
    request: Request,
    ctx: RequestContext = Depends(get_context),
    container: Container = Depends(get_container),
) -> Envelope[WhoAmIData]:
    data = WhoAmIData(
        owner_id=ctx.owner_id,
        request_id=ctx.request_id,
        mode=container.settings.app_mode,
    )
    return envelope(data, request, container, scope=ctx.owner_id)
