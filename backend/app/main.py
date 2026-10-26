"""FastAPI 应用组装：中间件、异常转换、路由与生命周期。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api.catalog import router as catalog_router
from backend.app.api.chat import router as chat_router
from backend.app.api.health import router as health_router
from backend.app.api.history import router as history_router
from backend.app.api.inventory import router as inventory_router
from backend.app.api.runs import router as runs_router
from backend.app.api.diagnostics import router as diagnostics_router
from backend.app.api.session import router as session_router
from backend.app.api.drafts import router as drafts_router
from backend.app.api.artifacts import router as artifacts_router
from backend.app.api.preferences import router as preferences_router
from backend.app.api.mutations import router as mutations_router
from backend.app.bootstrap import build_container
from backend.app.config import Settings, load_settings
from backend.app.contracts.common import (
    AppError,
    Envelope,
    ErrorBody,
    ErrorCodes,
    Meta,
)

logger = logging.getLogger(__name__)


def _fallback_meta(request: Request) -> Meta:
    return Meta(
        request_id=getattr(request.state, "request_id", "unknown"),
        data_source="none",
        as_of=datetime.now(timezone.utc),
        scope=getattr(request.state, "scope", "anonymous"),
    )


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
    data: object | None = None,
) -> JSONResponse:
    envelope: Envelope[object] = Envelope[object](
        ok=False,
        data=data,
        error=ErrorBody(code=code, message=message, retryable=retryable),
        meta=_fallback_meta(request),
    )
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = build_container(resolved)
        await container.start()
        app.state.container = container
        try:
            yield
        finally:
            await container.stop()

    app = FastAPI(
        title=resolved.app_name,
        version="0.1.0",
        lifespan=lifespan,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs" if resolved.app_mode == "local" else None,
        redoc_url=None,
    )
    app.state.settings = resolved

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = uuid4().hex
        request.state.scope = "anonymous"
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.http_status,
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            data=exc.data,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        parts = []
        for item in exc.errors()[:3]:
            location = ".".join(str(part) for part in item.get("loc", ()))
            parts.append(f"{location}: {item.get('msg', 'invalid value')}")
        return _error_response(
            request,
            status_code=422,
            code=ErrorCodes.VALIDATION_ERROR,
            message="; ".join(parts) or "request validation failed",
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = ErrorCodes.NOT_FOUND if exc.status_code == 404 else ErrorCodes.HTTP_ERROR
        message = "route not found" if exc.status_code == 404 else str(exc.detail)
        return _error_response(
            request,
            status_code=exc.status_code,
            code=code,
            message=message,
            retryable=False,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled API error: %s", type(exc).__name__)
        return _error_response(
            request,
            status_code=500,
            code=ErrorCodes.INTERNAL_ERROR,
            message="internal server error",
            retryable=False,
        )

    app.include_router(health_router)
    app.include_router(session_router)
    app.include_router(catalog_router)
    app.include_router(inventory_router)
    app.include_router(chat_router)
    app.include_router(history_router)
    app.include_router(runs_router)
    app.include_router(diagnostics_router)
    app.include_router(drafts_router)
    app.include_router(artifacts_router)
    app.include_router(preferences_router)
    app.include_router(mutations_router)
    return app


app = create_app()
