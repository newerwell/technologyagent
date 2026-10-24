"""/ready 依赖状态：DB ping、primary 与真实事务回滚探针。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any
from uuid import uuid4

from backend.app.config import Settings
from backend.app.contracts.common import Clock
from backend.app.repositories.mongo import MongoResources


class _RollbackProbe(Exception):
    pass


@dataclass
class ReadinessResult:
    ok: bool
    status: str
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    as_of: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "checks": self.checks}


class ReadinessService:
    def __init__(self, settings: Settings, mongo: MongoResources, clock: Clock) -> None:
        self._settings = settings
        self._mongo = mongo
        self._clock = clock

    def _disabled(self, reason: str) -> dict[str, Any]:
        return {"status": "disabled", "reason": reason}

    async def _probe_transaction(self) -> tuple[bool, str, float]:
        probe_id = f"p00-{uuid4().hex}"
        started = perf_counter()
        try:
            async with self._mongo.transaction() as session:
                await self._mongo.db["_health_probe"].insert_one(
                    {"_id": probe_id, "at": self._clock.now()}, session=session
                )
                raise _RollbackProbe
        except _RollbackProbe:
            pass
        latency = (perf_counter() - started) * 1000
        remaining = await self._mongo.db["_health_probe"].count_documents({"_id": probe_id})
        if remaining != 0:
            return False, "transaction probe left a document after rollback", latency
        return True, "commit/rollback transaction available", latency

    async def check(self) -> ReadinessResult:
        checks: dict[str, dict[str, Any]] = {}
        db_ok = False
        transaction_ok = False

        started = perf_counter()
        try:
            ping_ms = await asyncio.wait_for(self._mongo.ping(), timeout=4.0)
            hello = await asyncio.wait_for(self._mongo.hello(), timeout=4.0)
            primary = bool(hello.get("isWritablePrimary") or hello.get("ismaster"))
            db_ok = primary
            checks["db"] = {
                "status": "ok" if primary else "unavailable",
                "detail": "primary reachable" if primary else "connected but not primary",
                "latency_ms": round(ping_ms, 2),
            }
        except Exception as exc:  # noqa: BLE001 - readiness 要报告任意连接失败
            db_ok = False
            checks["db"] = {
                "status": "unavailable",
                "detail": f"{type(exc).__name__}: database unavailable",
                "latency_ms": round((perf_counter() - started) * 1000, 2),
            }

        if db_ok:
            try:
                transaction_ok, detail, latency = await asyncio.wait_for(
                    self._probe_transaction(), timeout=6.0
                )
            except Exception as exc:  # noqa: BLE001
                transaction_ok = False
                detail = f"{type(exc).__name__}: transaction probe failed"
                latency = 0.0
            checks["transaction"] = {
                "status": "ok" if transaction_ok else "unavailable",
                "detail": detail,
                "latency_ms": round(latency, 2),
            }
        else:
            checks["transaction"] = {
                "status": "unavailable",
                "detail": "skipped because database is unavailable",
                "latency_ms": 0.0,
            }

        if self._settings.model_mode == "fake":
            checks["model"] = {
                "status": "fake",
                "detail": "ScriptedModel is explicit; model_mode=fake",
                "latency_ms": 0.0,
            }
        elif self._settings.model_configured:
            checks["model"] = {
                "status": "configured",
                "detail": "live model configuration present; no paid probe on readiness",
                "latency_ms": 0.0,
            }
        else:
            checks["model"] = {
                "status": "unavailable",
                "detail": "MODEL_MODE=live but model name/key missing",
                "latency_ms": 0.0,
            }
        try:
            from backend.app.integrations.mcp import mcp_reachable
            mcp_ok = mcp_reachable("127.0.0.1", self._settings.mcp_port)
        except Exception:  # noqa: BLE001
            mcp_ok = False
        checks["mcp"] = {
            "status": "ok" if mcp_ok else "unavailable",
            "detail": (
                "MCP port reachable; tool calls still require per-run token"
                if mcp_ok
                else f"MCP server is not reachable on 127.0.0.1:{self._settings.mcp_port}"
            ),
            "latency_ms": 0.0,
        }
        checks["sandbox"] = self._disabled("sandbox execution is delivered in P06")

        all_ok = db_ok and transaction_ok
        return ReadinessResult(
            ok=all_ok,
            status="ready" if all_ok else "degraded",
            checks=checks,
            as_of=self._clock.now().isoformat(),
        )