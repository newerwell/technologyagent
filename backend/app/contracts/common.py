"""跨接入层共享的响应、上下文、时钟与错误契约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, field_validator

T = TypeVar("T")


class ErrorCodes:
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    LOCAL_SESSION_DISABLED = "LOCAL_SESSION_DISABLED"
    ACTIVE_RUN_EXISTS = "ACTIVE_RUN_EXISTS"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    STALE_APPROVAL = "STALE_APPROVAL"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    RUN_NOT_ACTIVE = "RUN_NOT_ACTIVE"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    HTTP_ERROR = "HTTP_ERROR"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
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


class PageQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page: int = 1
    page_size: int = 10

    @field_validator("page")
    @classmethod
    def _valid_page(cls, value: int) -> int:
        if value < 1:
            raise ValueError("page must be >= 1")
        return value

    @field_validator("page_size")
    @classmethod
    def _valid_page_size(cls, value: int) -> int:
        if value < 1 or value > 100:
            raise ValueError("page_size must be between 1 and 100")
        return value


class Page(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")

    records: list[T]
    total: int
    page: int
    page_size: int
    pages: int


def make_page(records: list[T], total: int, page: int, page_size: int) -> Page[T]:
    pages = (total + page_size - 1) // page_size if total else 0
    return Page[T](
        records=records,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )
