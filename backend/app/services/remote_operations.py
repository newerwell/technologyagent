"""Persistent, one-shot barrier for explicitly approved remote ERP mutations."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from pymongo.errors import DuplicateKeyError, OperationFailure

from backend.app.contracts.common import AppError, Clock, ErrorCodes, RequestContext
from backend.app.integrations.erp.client import ErpClient
from backend.app.repositories.indexes import APPROVALS
from backend.app.repositories.mongo import MongoResources
from backend.app.repositories.operations import OperationRepository
from backend.app.services.inventory import canonical_hash
from backend.app.contracts.mutations import parse_mutation_payload


def normalize_provider_scope(base_url: str) -> str:
    """Return a stable endpoint identity without credentials, query, or fragment."""
    parsed = urlsplit(base_url.strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        raise ValueError("ERP base URL must contain an http(s) scheme and hostname")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("ERP base URL has an invalid port") from exc
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = parsed.path.rstrip("/")
    return f"{scheme}://{host}{path}"


class RemoteOperationService:
    """Approvals, persistent intent, dispatch fence, and ERP request lifecycle.

    Production callers must pass only explicitly enabled actions. Bootstrap keeps this
    capability empty; tests enable a synthetic action against a loopback simulator.
    """

    def __init__(self, mongo: MongoResources, clock: Clock, client: ErpClient, *,
                 provider_scope: str | None = None,
                 write_actions: frozenset[str] = frozenset()) -> None:
        self.mongo, self.clock, self.client = mongo, clock, client
        configured_scope = normalize_provider_scope(client.base_url)
        if provider_scope is not None and normalize_provider_scope(provider_scope) != configured_scope:
            raise ValueError("provider scope must be derived from the configured ERP endpoint")
        self.provider_scope = configured_scope
        self.write_actions = write_actions
        self.operations = OperationRepository(mongo)

    def internal_action(self, action: str) -> str:
        return self.operations.remote_action_name(self.provider_scope, action)

    def _approved_payload(self, approval: dict[str, Any] | None, action: str,
                          payload: dict[str, Any], owner_id: str) -> dict[str, Any]:
        if (approval is None or approval.get("owner_id") != owner_id
                or approval.get("action") != action or approval.get("decision") != "approve"):
            raise AppError(ErrorCodes.APPROVAL_REQUIRED,
                           "a matching server-side approval decision is required", 403)
        if approval.get("status") != "pending":
            raise AppError(ErrorCodes.APPROVAL_REQUIRED, "approval is already consumed or inactive", 409)
        stored = parse_mutation_payload(action, approval.get("proposal_payload", {}))
        requested = parse_mutation_payload(action, payload)
        if stored != requested:
            raise AppError(ErrorCodes.STALE_APPROVAL,
                           "remote request differs from the approved proposal", 409)
        return requested

    @staticmethod
    def _has_external_id(value: Any) -> bool:
        return ((isinstance(value, str) and bool(value.strip()))
                or (type(value) is int and value >= 0))

    async def execute(self, approval_id: str, action: str, payload: dict[str, Any],
                      idempotency_key: str, ctx: RequestContext) -> dict[str, Any]:
        if action not in self.write_actions:
            raise AppError(ErrorCodes.UNSUPPORTED_OPERATION,
                           "remote write capability is disabled for this action", 405)
        if not idempotency_key:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "idempotency key is required", 422)
        try:
            normalized = parse_mutation_payload(action, payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "invalid remote mutation payload", 422) from exc
        payload_hash = canonical_hash({"approval_id": approval_id, "action": action,
                                       "payload": normalized})
        existing = await self.operations.get_remote_by_key(
            ctx.owner_id, self.provider_scope, action, idempotency_key)
        if existing is not None:
            return self._existing_result(existing, payload_hash, approval_id)

        now = self.clock.now()
        operation_id = f"op_{uuid4().hex}"
        document: dict[str, Any] = {
            "_id": operation_id, "owner_id": ctx.owner_id,
            "action": self.internal_action(action), "original_action": action,
            "provider_scope": self.provider_scope, "idempotency_key": idempotency_key,
            "payload_hash": payload_hash, "approval_id": approval_id,
            "correlation_id": operation_id, "status": "processing",
            "dispatch_state": "not_dispatched", "created_at": now, "updated_at": now,
        }
        if ctx.run_id:
            document["run_id"] = ctx.run_id

        try:
            async with self.mongo.transaction() as session:
                existing = await self.operations.get_remote_by_key(
                    ctx.owner_id, self.provider_scope, action, idempotency_key, session)
                if existing is not None:
                    return self._existing_result(existing, payload_hash, approval_id)
                approval = await self.mongo.db[APPROVALS].find_one(
                    {"_id": approval_id, "owner_id": ctx.owner_id}, session=session)
                self._approved_payload(approval, action, normalized, ctx.owner_id)
                document["approved_payload_hash"] = approval["payload_hash"]
                document["approval_version"] = approval.get("version")
                if approval.get("draft_version") is not None:
                    document["proposal_version"] = approval["draft_version"]
                if type(normalized.get("expected_version")) is int:
                    document["expected_version"] = normalized["expected_version"]
                await self.operations.create_remote(document, session=session)
                consumed = await self.mongo.db[APPROVALS].update_one(
                    {"_id": approval_id, "owner_id": ctx.owner_id, "action": action,
                     "status": "pending", "decision": "approve", "version": approval.get("version"),
                     "payload_hash": approval.get("payload_hash")},
                    {"$set": {"status": "consumed", "operation_id": operation_id,
                              "updated_at": now}}, session=session)
                if consumed.modified_count != 1:
                    raise AppError(ErrorCodes.STALE_APPROVAL,
                                   "approval changed while remote intent was being claimed", 409)
        except (DuplicateKeyError, OperationFailure) as exc:
            is_retryable_claim_race = isinstance(exc, DuplicateKeyError) or exc.has_error_label(
                "TransientTransactionError")
            if not is_retryable_claim_race:
                raise
            existing = await self.operations.get_remote_by_key(
                ctx.owner_id, self.provider_scope, action, idempotency_key)
            if existing is None:
                raise
            return self._existing_result(existing, payload_hash, approval_id)

        # The durable dispatch marker is committed before the only allowed POST.
        if not await self.operations.mark_remote_dispatched(operation_id, ctx.owner_id, self.clock.now()):
            return self._unknown(operation_id)
        try:
            result = await self.client.write(action, normalized, document["correlation_id"])
            if result.get("correlation_id") != document["correlation_id"]:
                raise ValueError("ERP response did not prove the operation correlation")
            if not self._has_external_id(result.get("id")):
                raise ValueError("ERP response did not include a stable external id")
            if result.get("status") not in {"accepted", "succeeded", "success", "completed"}:
                raise ValueError("ERP response did not confirm a successful mutation")
            saved = await self.operations.mark_remote_succeeded(
                operation_id, ctx.owner_id, result, self.clock.now())
            if not saved:
                raise RuntimeError("remote result could not be durably recorded")
            return {**result, "operation_id": operation_id, "status": "succeeded"}
        except Exception as exc:  # Any post-dispatch ambiguity requires lookup; never resend.
            await self.operations.mark_remote_unknown(
                operation_id, ctx.owner_id, self.clock.now(), type(exc).__name__)
            raise AppError(ErrorCodes.OUTCOME_UNKNOWN,
                           "remote write may have been applied; reconcile by correlation before retry", 409,
                           data={"operation_id": operation_id}) from exc

    def _existing_result(self, operation: dict[str, Any], payload_hash: str,
                         approval_id: str) -> dict[str, Any]:
        if operation.get("payload_hash") != payload_hash or operation.get("approval_id") != approval_id:
            raise AppError(ErrorCodes.IDEMPOTENCY_CONFLICT,
                           "idempotency key is already bound to a different payload or approval", 409)
        if operation.get("status") == "succeeded":
            return {**(operation.get("external_result") or operation.get("result") or {}),
                    "operation_id": operation["_id"], "status": "succeeded"}
        return self._unknown(operation["_id"])

    @staticmethod
    def _unknown(operation_id: str) -> dict[str, Any]:
        raise AppError(ErrorCodes.OUTCOME_UNKNOWN,
                       "remote operation is already claimed; reconcile it without replaying the write", 409,
                       data={"operation_id": operation_id})
