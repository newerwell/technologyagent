"""依赖组装与生命周期；这里知道具体实现，领域层不知道。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backend.app.config import Settings
from backend.app.contracts.common import Clock, SystemClock
from backend.app.repositories.indexes import ensure_indexes
from backend.app.repositories.mongo import MongoResources
from backend.app.repositories.sessions import SessionRepository
from backend.app.services.readiness import ReadinessService
from backend.app.services.sessions import SessionService

logger = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    clock: Clock
    mongo: MongoResources
    sessions: SessionService
    readiness: ReadinessService
    startup_errors: list[str] = field(default_factory=list)

    async def start(self) -> None:
        await self.mongo.connect()
        try:
            await ensure_indexes(self.mongo.db)
            self.settings.resolved_storage_root.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001 - DB 暂不可用时仍提供 /health
            message = f"{type(exc).__name__}: {exc}"
            self.startup_errors.append(message)
            logger.warning("P00 startup dependency check failed: %s", message)

    async def stop(self) -> None:
        await self.mongo.close()


def build_container(settings: Settings) -> Container:
    clock: Clock = SystemClock()
    mongo = MongoResources(settings)
    sessions = SessionService(settings, SessionRepository(mongo), clock)
    readiness = ReadinessService(settings, mongo, clock)
    return Container(
        settings=settings,
        clock=clock,
        mongo=mongo,
        sessions=sessions,
        readiness=readiness,
    )
