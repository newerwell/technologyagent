"""存活与就绪探针。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.app.api.dependencies import envelope, get_container
from backend.app.bootstrap import Container
from backend.app.contracts.common import (
    AppError,
    Envelope,
    ErrorCodes,
)

router = APIRouter(tags=["health"])


class HealthData(BaseModel):
    status: str
    app: str
    component: str


class ReadyData(BaseModel):
    status: str
    checks: dict[str, dict[str, Any]]


@router.get("/health", response_model=Envelope[HealthData])
async def health(
    request: Request,
    container: Container = Depends(get_container),
) -> Envelope[HealthData]:
    """仅表示进程存活，不检查数据库或模型。"""
    data = HealthData(status="ok", app=container.settings.app_name, component="api")
    return envelope(data, request, container)


@router.get("/ready", response_model=Envelope[ReadyData])
async def ready(
    request: Request,
    container: Container = Depends(get_container),
) -> Envelope[ReadyData]:
    result = await container.readiness.check()
    payload = ReadyData(status=result.status, checks=result.checks)
    if not result.ok:
        raise AppError(
            ErrorCodes.DEPENDENCY_UNAVAILABLE,
            "database or transaction capability is unavailable",
            http_status=503,
            retryable=True,
            data=payload.model_dump(mode="json"),
        )
    return envelope(payload, request, container)
