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
from backend.app.repositories.drafts import DraftRepository
from backend.app.repositories.orders import OrderRepository
from backend.app.services.drafts import DraftService
from backend.app.services.approvals import ApprovalService
from backend.app.services.mutations import MutationService
from backend.app.services.order_workflows import OrderWorkflowService
from backend.app.repositories.operations import OperationRepository
from backend.app.services.reconciliation import ReconciliationService
from backend.app.repositories.artifacts import ArtifactRepository
from backend.app.services.artifacts import ArtifactService
from backend.app.sandbox.runner import DockerSandbox
from backend.app.agent.tools.analysis import AnalysisRegistryFactory
from backend.app.repositories.preferences import PreferenceRepository
from backend.app.services.preferences import PreferenceService

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
    drafts: DraftService
    orders: OrderRepository
    approvals: ApprovalService
    mutations: MutationService
    order_workflows: OrderWorkflowService
    reconciliation: ReconciliationService
    runs: RunService
    chat: ChatService
    model_mode: str
    mcp_tokens: McpTokenService
    artifacts: ArtifactService
    sandbox: DockerSandbox
    preferences: PreferenceService
    startup_errors: list[str] = field(default_factory=list)

    async def start(self) -> None:
        await self.mongo.connect()
        try:
            await ensure_indexes(self.mongo.db)
            await self.mongo.configure_checkpointer()
            order_recovered = await self.order_workflows.recover_pending()
            if order_recovered:
                logger.info("recovered %s durable P04 resume(s)", order_recovered)
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
    sandbox = DockerSandbox()
    startup_errors: list[str] = []
    try:
        from backend.app.agent.specialists.policy import load_specialists
        from backend.app.agent.skill_loader import validate_skill_catalog
        specs = load_specialists()
        skills = validate_skill_catalog()
        for spec in specs.values():
            missing = set(spec.skills) - set(skills)
            if missing:
                raise ValueError(f"specialist {spec.name} references missing skills: {sorted(missing)}")
    except Exception as exc:
        startup_errors.append(f"specialist configuration unavailable: {type(exc).__name__}")
    artifacts = ArtifactService(ArtifactRepository(mongo), settings.resolved_storage_root, clock)
    sessions = SessionService(settings, SessionRepository(mongo), clock)
    readiness = ReadinessService(settings, mongo, clock, sandbox, startup_errors)
    catalog_repository = CatalogRepository(mongo)
    inventory_repository = InventoryRepository(mongo)
    catalog = CatalogService(catalog_repository, clock)
    inventory = InventoryService(inventory_repository, catalog_repository)
    replenishment = ReplenishmentService(catalog_repository, inventory_repository, clock)
    drafts = DraftService(mongo, catalog_repository, replenishment, clock)
    orders = OrderRepository(mongo)
    approvals = ApprovalService(mongo, clock)
    mutations = MutationService(mongo, clock, inventory_repository, orders)
    reconciliation = ReconciliationService(OperationRepository(mongo), orders, clock)
    runs = RunService(mongo, clock)
    preferences = PreferenceService(PreferenceRepository(mongo), mongo, clock)
    mcp_tokens = McpTokenService(McpTokenRepository(mongo), clock)
    if settings.model_mode == "live":
        model = build_model(settings)
        if model is None:
            raise RuntimeError("MODEL_MODE=live requires MODEL_BASE_URL, MODEL_NAME and MODEL_API_KEY")
    else:
        model = DemoScriptedModel()
    order_workflows = OrderWorkflowService(
        mongo, runs, drafts, approvals, mutations,
        model=model if settings.model_mode == "live" else None,
        catalog=catalog_repository,
        model_mode=settings.model_mode,
        preferences=preferences,
    )
    if settings.model_mode == "live":
        base_factory = McpRegistryFactory(
            f"http://127.0.0.1:{settings.mcp_port}/mcp", mcp_tokens
        )
        registry_factory = AnalysisRegistryFactory(base_factory, sandbox, artifacts, runs)
        executor = GraphExecutor(model, registry_factory, model_mode="live", runs=runs,
                                 order_workflows=order_workflows, preferences=preferences)
    else:
        async def local_factory(_ctx):
            return LocalToolRegistry(catalog_repository, inventory_repository, clock)
        registry_factory = AnalysisRegistryFactory(local_factory, sandbox, artifacts, runs)
        executor = GraphExecutor(model, registry_factory, model_mode="fake", runs=runs,
                                 order_workflows=order_workflows, preferences=preferences)
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
        drafts=drafts,
        orders=orders,
        approvals=approvals,
        mutations=mutations,
        order_workflows=order_workflows,
        reconciliation=reconciliation,
        runs=runs,
        chat=chat,
        model_mode=settings.model_mode,
        mcp_tokens=mcp_tokens,
        artifacts=artifacts,
        sandbox=sandbox,
        preferences=preferences,
        startup_errors=startup_errors,
    )
