"""订单操作结果核对；核对不执行新的业务写入。"""

from __future__ import annotations

from backend.app.contracts.common import AppError, Clock, ErrorCodes, RequestContext
from backend.app.repositories.operations import OperationRepository
from backend.app.repositories.orders import OrderRepository


class ReconciliationService:
    def __init__(self, operations: OperationRepository, orders: OrderRepository, clock: Clock) -> None:
        self._operations, self._orders, self._clock = operations, orders, clock

    async def reconcile(self, operation_id: str, ctx: RequestContext) -> dict:
        operation = await self._operations.get(ctx.owner_id, operation_id)
        if operation is None:
            raise AppError(ErrorCodes.NOT_FOUND, "operation not found", http_status=404)
        if operation.get("status") == "succeeded":
            return {"status": "succeeded", "operation_id": operation_id,
                    "result": operation.get("result")}

        order = await self._orders.get_by_operation(ctx.owner_id, operation_id)
        if order is not None:
            # Order + operation result are committed together. Seeing only one
            # side means the database needs manual inspection, never auto-retry.
            raise AppError(ErrorCodes.INTERNAL_ERROR,
                           "order exists without a succeeded operation record", http_status=409,
                           data={"operation_id": operation_id, "order_id": order.id})

        if operation.get("status") == "failed":
            return {"status": "failed", "operation_id": operation_id,
                    "error": operation.get("error")}
        expires = operation.get("lease_expires_at")
        if expires is not None and expires <= self._clock.now():
            return {"status": "retryable", "operation_id": operation_id,
                    "idempotency_key": operation["idempotency_key"],
                    "message": "事务中没有订单；可用原幂等键重试。"}
        return {"status": operation.get("status", "outcome_unknown"),
                "operation_id": operation_id, "retry_after_seconds": 2}
