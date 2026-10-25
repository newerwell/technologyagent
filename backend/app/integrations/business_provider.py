"""Composable business provider boundary and per-module source metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderCapabilities:
    data_source: str
    read: bool = True
    write: bool = False
    actions: frozenset[str] = frozenset()
    snapshot: bool = False


class BusinessProvider(Protocol):
    capabilities: ProviderCapabilities
    async def query(self, operation: str, **params: Any) -> Any: ...
    async def mutate(self, operation: str, payload: dict[str, Any], *, approved: bool) -> Any: ...


class UnsupportedProviderOperation(RuntimeError):
    code = "UNSUPPORTED_OPERATION"


class ProviderUnavailable(RuntimeError):
    code = "PROVIDER_UNAVAILABLE"


class UnavailableRemoteProvider:
    """Configured remote source without a valid client: fail closed, never use local data."""

    capabilities = ProviderCapabilities("remote_erp", read=False, write=False)

    async def query(self, operation: str, **params: Any) -> Any:
        raise ProviderUnavailable("remote ERP source is configured but unavailable")

    async def mutate(self, operation: str, payload: dict[str, Any], *, approved: bool) -> Any:
        raise ProviderUnavailable("remote ERP source is configured but unavailable")
