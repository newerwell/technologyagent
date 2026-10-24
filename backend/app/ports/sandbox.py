from typing import Protocol
from backend.app.contracts.artifacts import SandboxJob, SandboxResult
from backend.app.contracts.common import RequestContext


class SandboxPort(Protocol):
    async def execute(self, job: SandboxJob, ctx: RequestContext) -> SandboxResult: ...
    async def available(self) -> tuple[bool, str]: ...
