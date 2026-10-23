"""localhost 开发会话：随机 opaque token + HMAC 摘要存储。"""

from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta
from hashlib import sha256

from backend.app.config import Settings
from backend.app.contracts.common import Clock
from backend.app.repositories.sessions import SessionRecord, SessionRepository

SESSION_COOKIE = "ta_local_session"
LOCAL_OWNER_ID = "local-owner"


class SessionService:
    def __init__(
        self,
        settings: Settings,
        repository: SessionRepository,
        clock: Clock,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._clock = clock

    def _digest(self, raw_token: str) -> str:
        secret = self._settings.local_session_secret.get_secret_value().encode("utf-8")
        return hmac.new(secret, raw_token.encode("utf-8"), sha256).hexdigest()

    @property
    def ttl_seconds(self) -> int:
        return self._settings.session_ttl_hours * 3600

    async def create_local(self) -> tuple[SessionRecord, str]:
        raw_token = secrets.token_urlsafe(32)
        now = self._clock.now()
        record = SessionRecord(
            token_hash=self._digest(raw_token),
            owner_id=LOCAL_OWNER_ID,
            created_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
        )
        await self._repository.insert(record)
        return record, raw_token

    async def resolve(self, raw_token: str | None) -> SessionRecord | None:
        if not raw_token:
            return None
        record = await self._repository.find(self._digest(raw_token))
        if record is None:
            return None
        if record.expires_at <= self._clock.now():
            return None
        return record

    def expires_at_from(self, created_at: datetime) -> datetime:
        return created_at + timedelta(seconds=self.ttl_seconds)
