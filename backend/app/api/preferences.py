"""P07 用户显式偏好接口。"""

from fastapi import APIRouter, Depends, Request

from backend.app.api.dependencies import envelope, get_container, get_context
from backend.app.bootstrap import Container
from backend.app.contracts.common import RequestContext
from backend.app.contracts.preferences import RememberPreferenceRequest

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


@router.get("")
async def list_preferences(request: Request, ctx: RequestContext = Depends(get_context),
                          container: Container = Depends(get_container)):
    return envelope(await container.preferences.list(ctx.owner_id), request, container, scope=ctx.owner_id)


@router.put("")
async def remember_preference(body: RememberPreferenceRequest, request: Request,
                              ctx: RequestContext = Depends(get_context),
                              container: Container = Depends(get_container)):
    value = await container.preferences.remember(ctx.owner_id, body)
    return envelope(value, request, container, scope=ctx.owner_id)


@router.delete("/{key}")
async def delete_preference(key: str, request: Request, ctx: RequestContext = Depends(get_context),
                            container: Container = Depends(get_container)):
    deleted = await container.preferences.delete(ctx.owner_id, key)
    return envelope({"deleted": deleted}, request, container, scope=ctx.owner_id)
