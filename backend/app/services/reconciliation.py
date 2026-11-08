"""订单操作结果核对；核对不执行新的业务写入。"""

from __future__ import annotations

from backend.app.contracts.common import AppError, Clock, ErrorCodes, RequestContext
from backend.app.repositories.operations import OperationRepository
from backend.app.repositories.orders import OrderRepository
from backend.app.integrations.erp.client import ErpClient


class ReconciliationService:
    def __init__(self, operations: OperationRepository, orders: OrderRepository, clock: Clock,
                 remote_clients: dict[str, ErpClient] | None = None) -> None:
        self._operations, self._orders, self._clock = operations, orders, clock
        self._remote_clients = remote_clients or {}

    async def reconcile(self, operation_id: str, ctx: RequestContext) -> dict:
        operation = await self._operations.get(ctx.owner_id, operation_id)
        if operation is None:
            raise AppError(ErrorCodes.NOT_FOUND, "operation not found", http_status=404)
        if operation.get("status") == "succeeded":
            return {"status": "succeeded", "operation_id": operation_id,
                    "result": operation.get("result")}

        # Remote writes have no local order by design. They may only be reconciled
        # through the configured provider's lookup endpoint, never by a local retry.
        if operation.get("provider_scope"):
            return await self._reconcile_remote(operation, ctx.owner_id)

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

    async def _reconcile_remote(self, operation: dict, owner_id: str) -> dict:
        operation_id = str(operation["_id"])
        client = self._remote_clients.get(operation["provider_scope"])
        if client is None:
            return self._remote_unknown(operation_id)
        try:
            result = await client.lookup(operation["correlation_id"])
        except Exception:
            await self._operations.mark_remote_unknown(
                operation_id, owner_id, self._clock.now(), "LOOKUP_UNVERIFIED")
            return self._remote_unknown(operation_id)
        if (not isinstance(result, dict)
                or result.get("correlation_id") != operation.get("correlation_id")
                or not self._has_external_id(result.get("id"))
                or result.get("status") not in {"accepted", "succeeded", "success", "completed"}):
            await self._operations.mark_remote_unknown(
                operation_id, owner_id, self._clock.now(), "LOOKUP_UNVERIFIED")
            return self._remote_unknown(operation_id)
        if not await self._operations.mark_remote_succeeded(
                operation_id, owner_id, result, self._clock.now()):
            return self._remote_unknown(operation_id)
        return {"status": "succeeded", "operation_id": operation_id,
                "external_id": result.get("id"), "result": result,
                "retry_business_write": False}

    @staticmethod
    def _remote_unknown(operation_id: str) -> dict:
        return {"status": "outcome_unknown", "operation_id": operation_id,
                "retry_after_seconds": 2, "retry_business_write": False}

    @staticmethod
    def _has_external_id(value) -> bool:
        return ((isinstance(value, str) and bool(value.strip()))
                or (type(value) is int and value >= 0))
