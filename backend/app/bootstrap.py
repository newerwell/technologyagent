"""依赖组装与生命周期；这里知道具体实现，领域层不知道。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backend.app.config import Settings
from backend.app.contracts.common import Clock, SystemClock
from backend.app.repositories.catalog import CatalogRepository
from backend.app.repositories.indexes import ensure_indexes
from backend.app.repositories.inventory import InventoryRepository
from backend.app.repositories.mongo import MongoResources
from backend.app.repositories.sessions import SessionRepository
from backend.app.services.catalog import CatalogService, InventoryService
from backend.app.services.readiness import ReadinessService
from backend.app.services.chat import ChatService
from backend.app.services.replenishment import ReplenishmentService
from backend.app.services.runs import RunService
from backend.app.services.sessions import SessionService
from backend.app.agent.graph import GraphExecutor
from backend.app.agent.scripted_model import DemoScriptedModel
from backend.app.agent.local_tools import LocalToolRegistry
from backend.app.integrations.mcp import McpRegistryFactory
from backend.app.integrations.model import build_model
from backend.app.repositories.mcp_tokens import McpTokenRepository
from backend.app.services.mcp_tokens import McpTokenService

logger = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    clock: Clock
    mongo: MongoResources
    sessions: SessionService
    readiness: ReadinessService
    catalog: CatalogService
    inventory: InventoryService
    replenishment: ReplenishmentService
    runs: RunService
    chat: ChatService
    model_mode: str
    mcp_tokens: McpTokenService
    startup_errors: list[str] = field(default_factory=list)

    async def start(self) -> None:
        await self.mongo.connect()
        try:
            await ensure_indexes(self.mongo.db)
            recovered = await self.runs.recover_orphans()
            if recovered:
                logger.warning("recovered %s orphan P02 run(s) as failed", recovered)
            self.settings.resolved_storage_root.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001 - DB 暂不可用时仍提供 /health
            message = f"{type(exc).__name__}: {exc}"
            self.startup_errors.append(message)
            logger.warning("P00 startup dependency check failed: %s", message)

    async def stop(self) -> None:
        await self.chat.shutdown()
        await self.mongo.close()


def build_container(settings: Settings) -> Container:
    clock: Clock = SystemClock()
    mongo = MongoResources(settings)
    sessions = SessionService(settings, SessionRepository(mongo), clock)
    readiness = ReadinessService(settings, mongo, clock)
    catalog_repository = CatalogRepository(mongo)
    inventory_repository = InventoryRepository(mongo)
    catalog = CatalogService(catalog_repository, clock)
    inventory = InventoryService(inventory_repository)
    replenishment = ReplenishmentService(catalog_repository, inventory_repository, clock)
    runs = RunService(mongo, clock)
    mcp_tokens = McpTokenService(McpTokenRepository(mongo), clock)
    if settings.model_mode == "live":
        model = build_model(settings)
        if model is None:
            raise RuntimeError("MODEL_MODE=live requires MODEL_BASE_URL, MODEL_NAME and MODEL_API_KEY")
        registry_factory = McpRegistryFactory(
            f"http://127.0.0.1:{settings.mcp_port}/mcp", mcp_tokens
        )
        executor = GraphExecutor(model, registry_factory, model_mode="live")
    else:
        async def local_factory(_ctx):
            return LocalToolRegistry(catalog_repository, inventory_repository, clock)
        executor = GraphExecutor(DemoScriptedModel(), local_factory, model_mode="fake")
    chat = ChatService(runs, executor, max_active_seconds=180.0, model_mode=settings.model_mode)
    return Container(
        settings=settings,
        clock=clock,
        mongo=mongo,
        sessions=sessions,
        readiness=readiness,
        catalog=catalog,
        inventory=inventory,
        replenishment=replenishment,
        runs=runs,
        chat=chat,
        model_mode=settings.model_mode,
        mcp_tokens=mcp_tokens,
    )