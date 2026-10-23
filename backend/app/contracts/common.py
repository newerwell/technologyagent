"""跨接入层共享的响应、上下文、时钟与错误契约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ErrorCodes:
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    LOCAL_SESSION_DISABLED = "LOCAL_SESSION_DISABLED"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    HTTP_ERROR = "HTTP_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """统一业务错误。HTTP 接入层把它转换为共享 Envelope。"""

    def __init__(
        self,
        code: str,
        message: str,
        http_status: int = 400,
        retryable: bool = False,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable
        self.data = data


@dataclass(frozen=True, slots=True)
class RequestContext:
    """服务端解析出的可信调用上下文；身份不来自请求体。"""

    owner_id: str
    request_id: str
    run_id: str | None = None
    actor: str = "main"
    call_id: str | None = None


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock:
    """测试注入的固定时钟。"""

    def __init__(self, value: datetime) -> None:
        if value.tzinfo is None:
            raise ValueError("FixedClock requires an aware datetime")
        self._value = value.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self._value

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._value = self._value + timedelta(seconds=seconds)


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False


class Meta(BaseModel):
    model_config = ConfigDict(extra="allow")

    request_id: str
    data_source: str = "none"
    as_of: datetime
    scope: str = "anonymous"


class Envelope(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: T | None = None
    error: ErrorBody | None = None
    meta: Meta
