"""Explicit-capability remote ERP provider; it never falls back to local data."""

from __future__ import annotations

from typing import Any, Protocol

from backend.app.contracts.common import RequestContext
from backend.app.integrations.business_provider import ProviderCapabilities, UnsupportedProviderOperation
from backend.app.integrations.erp.client import ErpClient


class RemoteMutationExecutor(Protocol):
    async def execute(self, approval_id: str, action: str, payload: dict[str, Any],
                      idempotency_key: str, ctx: RequestContext) -> dict[str, Any]: ...


class ErpProvider:
    def __init__(self, client: ErpClient, *, read_actions: frozenset[str],
                 write_actions: frozenset[str] = frozenset(),
                 remote_operations: RemoteMutationExecutor | None = None) -> None:
        self.client = client
        self.read_actions = read_actions
        self.write_actions = write_actions
        self._remote_operations = remote_operations
        self.capabilities = ProviderCapabilities("remote_erp", bool(read_actions), bool(write_actions),
                                                 read_actions | write_actions)

    async def query(self, operation: str, *, remaining_budget: float | None = None, **params: Any) -> Any:
        if operation not in self.read_actions:
            raise UnsupportedProviderOperation(operation)
        return await self.client.read(operation, params, remaining_budget=remaining_budget)

    async def mutate(self, operation: str, payload: dict[str, Any], *,
                     approval_id: str | None = None, idempotency_key: str | None = None,
                     ctx: RequestContext | None = None, approved: bool | None = None,
                     correlation_id: str | None = None) -> Any:
        # `approved` is accepted temporarily for old callers, but never trusted.
        if (operation not in self.write_actions or self._remote_operations is None
                or not approval_id or not idempotency_key or ctx is None):
            raise UnsupportedProviderOperation(operation)
        business_payload = {key: value for key, value in payload.items()
                            if key not in {"approval_id", "idempotency_key"}}
        return await self._remote_operations.execute(
            approval_id, operation, business_payload, idempotency_key, ctx)
