"""Explicit-capability remote ERP provider; it never falls back to local data."""

from __future__ import annotations

from typing import Any

from backend.app.integrations.business_provider import ProviderCapabilities, UnsupportedProviderOperation
from backend.app.integrations.erp.client import ErpClient


class ErpProvider:
    def __init__(self, client: ErpClient, *, read_actions: frozenset[str], write_actions: frozenset[str] = frozenset()) -> None:
        self.client = client
        self.read_actions = read_actions
        self.write_actions = write_actions
        self.capabilities = ProviderCapabilities("remote_erp", bool(read_actions), bool(write_actions),
                                                 read_actions | write_actions)

    async def query(self, operation: str, **params: Any) -> Any:
        if operation not in self.read_actions:
            raise UnsupportedProviderOperation(operation)
        return await self.client.read(operation, params)

    async def mutate(self, operation: str, payload: dict[str, Any], *, approved: bool,
                     correlation_id: str | None = None) -> Any:
        if not approved:
            raise PermissionError("APPROVAL_REQUIRED")
        if operation not in self.write_actions or correlation_id is None:
            raise UnsupportedProviderOperation(operation)
        return await self.client.write(operation, payload, correlation_id)
