from typing import Protocol
from backend.app.contracts.artifacts import Artifact, CollectedOutput
from backend.app.contracts.common import RequestContext


class ArtifactPort(Protocol):
    async def register(self, output: CollectedOutput, ctx: RequestContext) -> Artifact: ...
    async def open(self, artifact_id: str, ctx: RequestContext) -> tuple[Artifact, bytes]: ...
