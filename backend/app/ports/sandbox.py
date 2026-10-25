from typing import Protocol
from backend.app.contracts.artifacts import SandboxJob, SandboxResult
from backend.app.contracts.common import RequestContext
from backend.app.agent.budget import RunBudget


class SandboxPort(Protocol):
    async def execute(self, job: SandboxJob, ctx: RequestContext, budget: RunBudget | None = None) -> SandboxResult: ...
    async def available(self) -> tuple[bool, str]: ...
