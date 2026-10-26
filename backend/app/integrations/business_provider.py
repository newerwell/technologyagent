"""Composable business provider boundary and per-module source metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from backend.app.contracts.common import AppError, ErrorCodes


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


def ensure_local_capability(providers: dict[str, Any], module: str, *, write: bool = False) -> str:
    """Guard local-backed routes against configured remote/snapshot source drift.

    These HTTP handlers currently return local Mongo projections. Until a mapped
    provider read is wired for a remote module, fail closed instead of labelling
    seed data as ERP data. A snapshot is readable but never writable.
    """
    provider = providers.get(module)
    capabilities = getattr(provider, "capabilities", None)
    source = getattr(capabilities, "data_source", "unknown")
    if source == "remote_erp":
        raise AppError(ErrorCodes.DEPENDENCY_UNAVAILABLE,
                       f"{module} remote provider is not available through this route", http_status=503,
                       retryable=True)
    if write and (source != "local_seed" or not getattr(capabilities, "write", False)):
        raise AppError(ErrorCodes.UNSUPPORTED_OPERATION,
                       f"{module} provider does not permit local writes", http_status=405)
    return source


class UnavailableRemoteProvider:
    """Configured remote source without a valid client: fail closed, never use local data."""

    capabilities = ProviderCapabilities("remote_erp", read=False, write=False)

    async def query(self, operation: str, **params: Any) -> Any:
        raise ProviderUnavailable("remote ERP source is configured but unavailable")

    async def mutate(self, operation: str, payload: dict[str, Any], *, approved: bool) -> Any:
        raise ProviderUnavailable("remote ERP source is configured but unavailable")
