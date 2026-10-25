"""按artifact_id下载已授权产物。"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from backend.app.api.dependencies import get_container, get_context
from backend.app.bootstrap import Container
from backend.app.contracts.common import RequestContext
from backend.app.contracts.common import Envelope
from backend.app.contracts.artifacts import ArtifactListItem
from backend.app.api.dependencies import envelope

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.get("", response_model=Envelope[list[ArtifactListItem]])
async def list_thread_artifacts(
    request: Request,
    thread_id: str = Query(min_length=1, max_length=128),
    container: Container = Depends(get_container),
    ctx: RequestContext = Depends(get_context),
) -> Envelope[list[ArtifactListItem]]:
    items = await container.artifacts.list_for_thread(thread_id, ctx)
    return envelope(items, request, container, scope=ctx.owner_id, data_source="mongo")


@router.get("/{artifact_id}")
async def download_artifact(
    artifact_id: str,
    container: Container = Depends(get_container),
    ctx: RequestContext = Depends(get_context),
) -> Response:
    artifact, content = await container.artifacts.open(artifact_id, ctx)
    filename = quote(artifact.filename)
    return Response(content=content, media_type=artifact.mime, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    })


@router.get("/{artifact_id}/preview")
async def preview_artifact(
    artifact_id: str,
    container: Container = Depends(get_container),
    ctx: RequestContext = Depends(get_context),
) -> Response:
    artifact, content = await container.artifacts.open(artifact_id, ctx)
    if artifact.mime not in {"image/png", "text/html", "text/markdown", "text/csv", "application/json"}:
        from backend.app.contracts.common import AppError, ErrorCodes
        raise AppError(ErrorCodes.VALIDATION_ERROR, "artifact preview type is unsupported", http_status=422)
    disposition = "inline" if artifact.mime == "image/png" else "attachment"
    return Response(content=content, media_type=artifact.mime, headers={
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(artifact.filename)}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    })
