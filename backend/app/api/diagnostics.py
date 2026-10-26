"""Owner-scoped read-only execution diagnostics."""

from fastapi import APIRouter, Depends, Request

from backend.app.api.dependencies import envelope, get_container, get_context
from backend.app.bootstrap import Container
from backend.app.contracts.common import RequestContext

router = APIRouter(prefix="/api/runs", tags=["diagnostics"])


@router.get("/{run_id}/trace")
async def run_trace(run_id: str, request: Request,
                    ctx: RequestContext = Depends(get_context),
                    container: Container = Depends(get_container)):
    data = await container.tracing.summary(run_id, ctx)
    return envelope(data.model_dump(mode="json"), request, container, scope=ctx.owner_id,
                    data_source="mongo")
