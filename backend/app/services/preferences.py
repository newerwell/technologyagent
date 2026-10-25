"""用户显式偏好服务；显式字段优先，偏好不能改变业务有效性校验。"""

from __future__ import annotations

from typing import Any

from backend.app.contracts.common import AppError, Clock, ErrorCodes
from backend.app.contracts.preferences import RememberPreferenceRequest
from backend.app.repositories.preferences import PreferenceRepository
from backend.app.repositories.mongo import MongoResources


class PreferenceService:
    KEYS = frozenset({"default_warehouse", "preferred_supplier", "max_lead_days"})

    def __init__(self, repository: PreferenceRepository, mongo: MongoResources, clock: Clock):
        self._repository, self._mongo, self._clock = repository, mongo, clock

    async def list(self, owner_id: str) -> dict[str, Any]:
        return await self._repository.list(owner_id)

    async def remember(self, owner_id: str, request: RememberPreferenceRequest) -> dict[str, Any]:
        key, value = request.key, request.value
        if key == "default_warehouse":
            if not isinstance(value, str) or not value.strip():
                raise AppError(ErrorCodes.VALIDATION_ERROR, "仓库编号无效", http_status=422)
            warehouse = await self._mongo.db["inventories"].find_one({"warehouse_id": value.strip()})
            if warehouse is None:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "仓库不存在", http_status=422)
            value = value.strip()
        elif key == "preferred_supplier":
            if not isinstance(value, str) or not value.strip():
                raise AppError(ErrorCodes.VALIDATION_ERROR, "供应商编号无效", http_status=422)
            supplier = await self._mongo.db["suppliers"].find_one({"_id": value.strip(), "status": "active"})
            if supplier is None:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "供应商不存在或已停用", http_status=422)
            value = value.strip()
        elif key == "max_lead_days":
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 365:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "最长交期必须是0到365的整数", http_status=422)
        return await self._repository.remember(owner_id, key, value, self._clock.now())

    async def delete(self, owner_id: str, key: str) -> bool:
        if key not in self.KEYS:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "不支持的偏好字段", http_status=422)
        return await self._repository.delete(owner_id, key)

    async def effective(self, owner_id: str, explicit: dict[str, Any]) -> dict[str, Any]:
        stored = await self.list(owner_id)
        # The request wins for this run and is never written back as memory.
        return {**stored, **{key: value for key, value in explicit.items() if value is not None}}
