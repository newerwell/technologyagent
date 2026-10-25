"""Bounded HTTPX ERP client. Reads may retry; writes never retry automatically."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx


class ErpOutcomeUnknown(RuntimeError):
    code = "OUTCOME_UNKNOWN"


class ErpClient:
    def __init__(self, base_url: str, *, token: str | None = None, timeout_seconds: float = 5.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._timeout = timeout_seconds
        self._transport = transport
        self._unknown_write_correlations: set[tuple[str, str]] = set()

    async def read(self, operation: str, params: dict[str, Any] | None = None,
                   *, remaining_budget: float | None = None) -> dict[str, Any]:
        attempts = 0
        last: Exception | None = None
        while attempts < 3:
            if remaining_budget is not None and remaining_budget <= 0:
                raise TimeoutError("run budget exhausted before ERP read")
            attempts += 1
            timeout = min(self._timeout, remaining_budget) if remaining_budget is not None else self._timeout
            try:
                async with httpx.AsyncClient(base_url=self._base_url, headers=self._headers,
                                             timeout=timeout, transport=self._transport) as client:
                    response = await client.get(f"/{operation.lstrip('/')}", params=params)
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError("ERP response must be an object")
                    return payload
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
                if attempts == 3:
                    break
                if remaining_budget is not None:
                    remaining_budget -= timeout
        raise TimeoutError("ERP read failed after bounded retries") from last

    async def write(self, operation: str, payload: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        key = (operation, correlation_id)
        if key in self._unknown_write_correlations:
            raise ErpOutcomeUnknown("this correlation already has an unknown outcome; lookup it before any retry")
        try:
            async with httpx.AsyncClient(base_url=self._base_url, headers=self._headers,
                                         timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(f"/{operation.lstrip('/')}", json=payload,
                                             headers={"Idempotency-Key": correlation_id})
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("ERP response must be an object")
                return data
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            self._unknown_write_correlations.add(key)
            raise ErpOutcomeUnknown("ERP write response was lost; reconcile correlation_id before retry") from exc

    async def lookup(self, correlation_id: str, operation: str = "operations/by-correlation") -> dict[str, Any] | None:
        try:
            return await self.read(operation, {"correlation_id": correlation_id})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ErpOutcomeUnknown("ERP lookup returned ordinary 404; it does not prove the write had no effect") from exc
            raise
