"""P03 短期 MCP 身份令牌：只允许 owner/run/actor 对应当前执行。"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from backend.app.contracts.common import Clock, RequestContext
from backend.app.repositories.mcp_tokens import McpIdentity, McpTokenRepository


class McpTokenService:
    def __init__(self, repository: McpTokenRepository, clock: Clock, *, ttl_seconds: int = 300) -> None:
        self._repository = repository
        self._clock = clock
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def _digest(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def issue(self, ctx: RequestContext) -> str:
        if not ctx.run_id:
            raise ValueError("MCP token requires run_id")
        raw = secrets.token_urlsafe(32)
        now = self._clock.now()
        await self._repository.insert(
            McpIdentity(
                token_hash=self._digest(raw),
                owner_id=ctx.owner_id,
                run_id=ctx.run_id,
                actor=ctx.actor,
                created_at=now,
                expires_at=now + timedelta(seconds=self._ttl_seconds),
            )
        )
        return raw

    async def resolve(self, raw: str | None) -> McpIdentity | None:
        if not raw:
            return None
        identity = await self._repository.find(self._digest(raw))
        if identity is None or identity.expires_at <= self._clock.now():
            return None
        return identity

    async def revoke(self, raw: str) -> None:
        await self._repository.delete(self._digest(raw))
