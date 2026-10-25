"""Local Mongo business adapter; mutations require the approved mutation service."""

from __future__ import annotations

from typing import Any

from backend.app.integrations.business_provider import ProviderCapabilities, UnsupportedProviderOperation


class LocalProvider:
    def __init__(self, services: dict[str, Any], *, snapshot: bool = False) -> None:
        self.services = services
        self.capabilities = ProviderCapabilities(
            "local_snapshot" if snapshot else "local_seed", True, not snapshot,
            frozenset() if snapshot else frozenset({"approved_mutation"}), snapshot,
        )

    async def query(self, operation: str, **params: Any) -> Any:
        prefix = operation.split("_", 1)[0]
        module = {"supplier": "catalog", "part": "catalog", "inventory": "inventory",
                  "order": "orders"}.get(prefix, prefix)
        service = self.services.get(module)
        method = getattr(service, operation, None) if service else None
        if method is None:
            raise UnsupportedProviderOperation(operation)
        return await method(**params)

    async def mutate(self, operation: str, payload: dict[str, Any], *, approved: bool) -> Any:
        if not self.capabilities.write:
            raise UnsupportedProviderOperation("local snapshot is read-only")
        if not approved:
            raise PermissionError("APPROVAL_REQUIRED")
        service = self.services.get("mutations")
        method = getattr(service, operation, None) if service else None
        if method is None:
            raise UnsupportedProviderOperation(operation)
        return await method(**payload)
