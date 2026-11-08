"""R6 persistent remote write barrier against a real test Mongo and loopback ERP."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from pydantic import SecretStr
from pymongo import MongoClient

from backend.app.config import Settings
from backend.app.contracts.common import AppError, RequestContext, SystemClock
from backend.app.integrations.erp.client import ErpClient
from backend.app.repositories.mongo import MongoResources
from backend.app.repositories.operations import OperationRepository
from backend.app.services.reconciliation import ReconciliationService
from backend.app.services.remote_operations import (
    RemoteOperationService,
    normalize_provider_scope,
)


class _Simulator:
    def __init__(self):
        self.posts: list[dict] = []
        self.external: dict[str, dict] = {}
        self.lose_post_response = False
        self.omit_external_id = False
        self.lookup_status = 200

        simulator = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                correlation = self.headers["Idempotency-Key"]
                simulator.posts.append({"action": self.path.lstrip("/"), "payload": body,
                                        "correlation_id": correlation})
                result = {"id": f"external-{len(simulator.posts)}", "status": "accepted",
                          "correlation_id": correlation}
                if simulator.omit_external_id:
                    result.pop("id")
                simulator.external[correlation] = result
                if simulator.lose_post_response:
                    self.close_connection = True
                    return
                raw = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if simulator.lookup_status != 200:
                    self.send_response(simulator.lookup_status)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                from urllib.parse import parse_qs, urlparse
                correlation = parse_qs(urlparse(self.path).query).get("correlation_id", [""])[0]
                result = simulator.external.get(correlation)
                if result is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                raw = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _run(client, awaitable):
    async def invoke():
        return await awaitable
    return client.portal.call(invoke)


def _replay_remote_in_fresh_process(uri: str, database: str, base_url: str, scope: str,
                                   approval_id: str, action: str, payload: dict,
                                   key: str, owner_id: str, queue) -> None:
    async def invoke():
        settings = Settings(app_mode="local", mongodb_uri=SecretStr(uri), mongodb_database=database,
                            model_mode="fake", model_name="", model_api_key=None,
                            local_session_secret=SecretStr("test-only-local-session-secret"),
                            storage_root=Path("storage") / "test")
        mongo = await MongoResources.open(settings)
        try:
            service = RemoteOperationService(mongo, SystemClock(), ErpClient(base_url),
                                             provider_scope=scope, write_actions=frozenset({action}))
            result = await service.execute(approval_id, action, payload, key,
                                           RequestContext(owner_id, "r6-process-replay"))
            return result
        finally:
            await mongo.close()

    try:
        queue.put({"result": asyncio.run(invoke())})
    except Exception as exc:  # return child errors to the parent as test evidence  # noqa: BLE001
        queue.put({"error": f"{type(exc).__name__}: {exc}"})


def _crash_process_after_dispatch_marker(uri: str, database: str, base_url: str,
                                         approval_id: str, key: str, owner_id: str) -> None:
    async def invoke():
        settings = Settings(app_mode="local", mongodb_uri=SecretStr(uri), mongodb_database=database,
                            model_mode="fake", model_name="", model_api_key=None,
                            local_session_secret=SecretStr("test-only-local-session-secret"),
                            storage_root=Path("storage") / "test")
        mongo = await MongoResources.open(settings)

        class CrashClient(ErpClient):
            async def write(self, *_args, **_kwargs):
                # This is reached only after the Mongo dispatch marker commits.
                os._exit(23)

        client = CrashClient(base_url)
        service = RemoteOperationService(mongo, SystemClock(), client,
                                         write_actions=frozenset({"supplier_create"}))
        await service.execute(approval_id, "supplier_create", {"code": "R6-CRASH", "name": "R6 crash"},
                              key, RequestContext(owner_id, "r6-crash-child"))

    asyncio.run(invoke())


def test_provider_scope_is_normalized_without_credentials_query_or_fragment():
    assert normalize_provider_scope("HTTPS://user:secret@ERP.Example:443/api/?tenant=x#frag") == \
        normalize_provider_scope("https://erp.example/api")
    assert normalize_provider_scope("https://[2001:db8::1]:443/api/") == "https://[2001:db8::1]/api"
    with pytest.raises(ValueError, match="derived from the configured ERP endpoint"):
        RemoteOperationService(None, None, ErpClient("https://erp.example/api"),
                               provider_scope="https://other.example/api")


def test_remote_dispatch_requires_matching_server_approval(seeded_client):
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", "r6-approval", run_id="r6-approval")
    approved_payload = {"code": "R6-APPROVED", "name": "Approved supplier"}
    approval = _run(seeded_client, container.approvals.request_mutation(
        "supplier_create", approved_payload, ctx))
    with _Simulator() as simulator:
        service = RemoteOperationService(container.mongo, container.clock, ErpClient(simulator.url),
                                         provider_scope=normalize_provider_scope(simulator.url),
                                         write_actions=frozenset({"supplier_create"}))
        with pytest.raises(AppError) as unapproved:
            _run(seeded_client, service.execute(approval["approval_id"], "supplier_create",
                                                approved_payload, "r6-unapproved-key", ctx))
        assert unapproved.value.code == "APPROVAL_REQUIRED"
        _run(seeded_client, container.approvals.resolve_mutation(
            approval["approval_id"], "approve", "r6-approval-decision", ctx))
        with pytest.raises(AppError) as modified:
            _run(seeded_client, service.execute(approval["approval_id"], "supplier_create",
                                                {"code": "R6-CHANGED", "name": "Changed"},
                                                "r6-modified-key", ctx))
        assert modified.value.code == "STALE_APPROVAL"
        assert len(simulator.posts) == 0
        op_count = _run(seeded_client, container.mongo.db.operations.count_documents(
            {"provider_scope": service.provider_scope}))
        assert op_count == 0


def test_remote_dispatch_rejects_tampered_proposal_even_when_request_matches_tampering(seeded_client):
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", "r6-tampered-proposal", run_id="r6-tampered-proposal")
    original = {"code": "R6-ORIGINAL", "name": "Original supplier"}
    changed = {"code": "R6-CHANGED", "name": "Changed supplier"}
    approval = _run(seeded_client, container.approvals.request_mutation("supplier_create", original, ctx))
    _run(seeded_client, container.approvals.resolve_mutation(
        approval["approval_id"], "approve", "r6-tampered-proposal-decision", ctx))

    with _Simulator() as simulator:
        service = RemoteOperationService(container.mongo, container.clock, ErpClient(simulator.url),
                                         write_actions=frozenset({"supplier_create"}))
        _run(seeded_client, container.mongo.db.approvals.update_one(
            {"_id": approval["approval_id"]}, {"$set": {"proposal_payload": changed}}))

        with pytest.raises(AppError) as rejected:
            _run(seeded_client, service.execute(approval["approval_id"], "supplier_create", changed,
                                                "r6-tampered-proposal-key", ctx))

        assert rejected.value.code == "STALE_APPROVAL"
        assert simulator.posts == []
        assert _run(seeded_client, container.mongo.db.operations.count_documents(
            {"owner_id": ctx.owner_id, "provider_scope": service.provider_scope})) == 0
        stored = _run(seeded_client, container.mongo.db.approvals.find_one({"_id": approval["approval_id"]}))
        assert stored["status"] == "pending"
        assert stored["payload_hash"] == approval["payload_hash"]


@pytest.mark.parametrize("field,value", [
    ("version", 0), ("version", True), ("draft_version", None), ("draft_version", 2),
])
def test_remote_dispatch_rejects_invalid_proposal_versions_before_operation_or_post(seeded_client, field, value):
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", f"r6-invalid-version-{field}-{value}", run_id="r6-invalid-version")
    payload = {"code": f"R6-V-{field}-{value}", "name": "Versioned supplier"}
    approval = _run(seeded_client, container.approvals.request_mutation("supplier_create", payload, ctx))
    _run(seeded_client, container.approvals.resolve_mutation(
        approval["approval_id"], "approve", f"decision-{field}-{value}", ctx))

    with _Simulator() as simulator:
        service = RemoteOperationService(container.mongo, container.clock, ErpClient(simulator.url),
                                         write_actions=frozenset({"supplier_create"}))
        _run(seeded_client, container.mongo.db.approvals.update_one(
            {"_id": approval["approval_id"]}, {"$set": {field: value}}))

        with pytest.raises(AppError) as rejected:
            _run(seeded_client, service.execute(approval["approval_id"], "supplier_create", payload,
                                                f"key-{field}-{value}", ctx))

        assert rejected.value.code == "STALE_APPROVAL"
        assert simulator.posts == []
        assert _run(seeded_client, container.mongo.db.operations.count_documents(
            {"owner_id": ctx.owner_id, "provider_scope": service.provider_scope})) == 0
        stored = _run(seeded_client, container.mongo.db.approvals.find_one({"_id": approval["approval_id"]}))
        assert stored["status"] == "pending"


@pytest.mark.parametrize("invalid_hash", [None, ""])
def test_remote_dispatch_rejects_missing_or_empty_approval_hash_before_operation_or_post(seeded_client, invalid_hash):
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", f"r6-invalid-hash-{invalid_hash}", run_id="r6-invalid-hash")
    payload = {"code": f"R6-HASH-{invalid_hash}", "name": "Hashed supplier"}
    approval = _run(seeded_client, container.approvals.request_mutation("supplier_create", payload, ctx))
    _run(seeded_client, container.approvals.resolve_mutation(
        approval["approval_id"], "approve", f"decision-hash-{invalid_hash}", ctx))

    with _Simulator() as simulator:
        service = RemoteOperationService(container.mongo, container.clock, ErpClient(simulator.url),
                                         write_actions=frozenset({"supplier_create"}))
        _run(seeded_client, container.mongo.db.approvals.update_one(
            {"_id": approval["approval_id"]}, {"$set": {"payload_hash": invalid_hash}}))

        with pytest.raises(AppError) as rejected:
            _run(seeded_client, service.execute(approval["approval_id"], "supplier_create", payload,
                                                f"key-hash-{invalid_hash}", ctx))

        assert rejected.value.code == "STALE_APPROVAL"
        assert simulator.posts == []
        assert _run(seeded_client, container.mongo.db.operations.count_documents(
            {"owner_id": ctx.owner_id, "provider_scope": service.provider_scope})) == 0


def test_remote_dispatch_is_persistent_one_shot_across_service_rebuild(seeded_client):
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", "r6", run_id="r6")
    payload = {"code": "R6-SUP", "name": "R6 supplier"}
    approval = _run(seeded_client, container.approvals.request_mutation("supplier_create", payload, ctx))
    _run(seeded_client, container.approvals.resolve_mutation(approval["approval_id"], "approve", "r6-decision", ctx))

    with _Simulator() as simulator:
        scope = normalize_provider_scope(simulator.url)
        first = RemoteOperationService(container.mongo, container.clock, ErpClient(simulator.url),
                                       provider_scope=scope, write_actions=frozenset({"supplier_create"}))
        result = _run(seeded_client, first.execute(approval["approval_id"], "supplier_create", payload,
                                                   "r6-key", ctx))
        # A new service and HTTP client must rely on Mongo, not process-local state.
        rebuilt = RemoteOperationService(container.mongo, container.clock, ErpClient(simulator.url),
                                         provider_scope=scope, write_actions=frozenset({"supplier_create"}))
        replay = _run(seeded_client, rebuilt.execute(approval["approval_id"], "supplier_create", payload,
                                                     "r6-key", ctx))
        assert replay == result
        assert len(simulator.posts) == 1

        process_context = multiprocessing.get_context("spawn")
        queue = process_context.Queue()
        process = process_context.Process(
            target=_replay_remote_in_fresh_process,
            args=(container.settings.mongodb_uri.get_secret_value(), container.settings.mongodb_database,
                  simulator.url, scope, approval["approval_id"], "supplier_create", payload,
                  "r6-key", ctx.owner_id, queue))
        process.start()
        process.join(timeout=30)
        assert process.exitcode == 0
        process_result = queue.get(timeout=3)
        assert "error" not in process_result, process_result
        assert process_result["result"] == result
        assert len(simulator.posts) == 1

        sync = MongoClient(container.settings.mongodb_uri.get_secret_value())
        try:
            db = sync[container.settings.mongodb_database]
            op = db.operations.find_one({"owner_id": ctx.owner_id, "provider_scope": scope,
                                        "idempotency_key": "r6-key"})
            assert op["original_action"] == "supplier_create"
            assert op["approval_id"] == approval["approval_id"]
            assert op["approved_payload_hash"] == approval["payload_hash"]
            assert op["approval_version"] == 1 and op["proposal_version"] == 1
            assert op["dispatch_state"] == "dispatched"
            assert op["external_id"] == result["id"]
            assert db.approvals.find_one({"_id": approval["approval_id"]})["operation_id"] == op["_id"]
            assert db.suppliers.count_documents({"code": payload["code"]}) == 0
        finally:
            sync.close()

        with pytest.raises(AppError) as conflict:
            _run(seeded_client, rebuilt.execute(approval["approval_id"], "supplier_create",
                                                 {"code": "R6-OTHER", "name": "other"}, "r6-key", ctx))
        assert conflict.value.code == "IDEMPOTENCY_CONFLICT"

        other_approval = _run(seeded_client, container.approvals.request_mutation(
            "supplier_create", payload,
            RequestContext(ctx.owner_id, "r6-second-approval", run_id="r6-second-approval")))
        _run(seeded_client, container.approvals.resolve_mutation(
            other_approval["approval_id"], "approve", "r6-second-approval-decision", ctx))
        with pytest.raises(AppError) as approval_conflict:
            _run(seeded_client, rebuilt.execute(other_approval["approval_id"], "supplier_create",
                                                payload, "r6-key", ctx))
        assert approval_conflict.value.code == "IDEMPOTENCY_CONFLICT"
        assert len(simulator.posts) == 1


def test_expired_remote_lease_does_not_reclaim_or_post_again(seeded_client):
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", "r6-expired", run_id="r6-expired")
    payload = {"code": "R6-EXP", "name": "R6 expired"}
    approval = _run(seeded_client, container.approvals.request_mutation("supplier_create", payload, ctx))
    _run(seeded_client, container.approvals.resolve_mutation(approval["approval_id"], "approve", "r6-exp-decision", ctx))
    with _Simulator() as simulator:
        service = RemoteOperationService(container.mongo, container.clock, ErpClient(simulator.url),
                                         provider_scope=normalize_provider_scope(simulator.url),
                                         write_actions=frozenset({"supplier_create"}))
        _run(seeded_client, service.execute(approval["approval_id"], "supplier_create", payload, "r6-exp-key", ctx))
        op = _run(seeded_client, OperationRepository(container.mongo).get_by_key(
            ctx.owner_id, service.internal_action("supplier_create"), "r6-exp-key"))
        _run(seeded_client, container.mongo.db.operations.update_one(
            {"_id": op["_id"]}, {"$set": {"status": "outcome_unknown",
                                               "lease_expires_at": container.clock.now()}}))
        rebuilt = RemoteOperationService(container.mongo, container.clock, ErpClient(simulator.url),
                                         provider_scope=normalize_provider_scope(simulator.url),
                                         write_actions=frozenset({"supplier_create"}))
        with pytest.raises(AppError) as unknown:
            _run(seeded_client, rebuilt.execute(approval["approval_id"], "supplier_create",
                                                payload, "r6-exp-key", ctx))
        assert unknown.value.code == "OUTCOME_UNKNOWN"
        assert len(simulator.posts) == 1


def test_lost_remote_response_reconciles_by_lookup_without_repost(seeded_client):
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", "r6-lost", run_id="r6-lost")
    payload = {"code": "R6-LOST", "name": "R6 lost response"}
    approval = _run(seeded_client, container.approvals.request_mutation("supplier_create", payload, ctx))
    _run(seeded_client, container.approvals.resolve_mutation(approval["approval_id"], "approve", "r6-lost-decision", ctx))
    with _Simulator() as simulator:
        simulator.lose_post_response = True
        service = RemoteOperationService(container.mongo, container.clock, ErpClient(simulator.url),
                                         provider_scope=normalize_provider_scope(simulator.url),
                                         write_actions=frozenset({"supplier_create"}))
        with pytest.raises(AppError) as unknown:
            _run(seeded_client, service.execute(approval["approval_id"], "supplier_create", payload, "r6-lost-key", ctx))
        assert unknown.value.code == "OUTCOME_UNKNOWN"
        assert len(simulator.posts) == 1

        simulator.lose_post_response = False
        rebuilt = RemoteOperationService(container.mongo, container.clock, ErpClient(simulator.url),
                                         provider_scope=normalize_provider_scope(simulator.url),
                                         write_actions=frozenset({"supplier_create"}))
        operation = _run(seeded_client, OperationRepository(container.mongo).get_by_key(
            ctx.owner_id, rebuilt.internal_action("supplier_create"), "r6-lost-key"))
        reconciliation = ReconciliationService(OperationRepository(container.mongo), container.orders,
                                                container.clock,
                                                {normalize_provider_scope(simulator.url): ErpClient(simulator.url)})
        result = _run(seeded_client, reconciliation.reconcile(operation["_id"], ctx))
        assert result["status"] == "succeeded"
        assert result["external_id"] == "external-1"
        assert len(simulator.posts) == 1


def test_remote_lookup_404_stays_unknown_even_without_local_order(seeded_client):
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", "r6-404", run_id="r6-404")
    payload = {"code": "R6-404", "name": "R6 not found"}
    approval = _run(seeded_client, container.approvals.request_mutation("supplier_create", payload, ctx))
    _run(seeded_client, container.approvals.resolve_mutation(approval["approval_id"], "approve", "r6-404-decision", ctx))
    with _Simulator() as simulator:
        simulator.lose_post_response = True
        service = RemoteOperationService(container.mongo, container.clock, ErpClient(simulator.url),
                                         provider_scope=normalize_provider_scope(simulator.url),
                                         write_actions=frozenset({"supplier_create"}))
        with pytest.raises(AppError):
            _run(seeded_client, service.execute(approval["approval_id"], "supplier_create", payload,
                                                "r6-404-key", ctx))
        op = _run(seeded_client, OperationRepository(container.mongo).get_by_key(
            ctx.owner_id, service.internal_action("supplier_create"), "r6-404-key"))
        simulator.external.clear()
        reconciliation = ReconciliationService(OperationRepository(container.mongo), container.orders,
                                                container.clock,
                                                {normalize_provider_scope(simulator.url): ErpClient(simulator.url)})
        result = _run(seeded_client, reconciliation.reconcile(op["_id"], ctx))
        assert result["status"] == "outcome_unknown"
        assert result["retry_business_write"] is False
        assert len(simulator.posts) == 1


def test_concurrent_remote_claim_dispatches_at_most_once(seeded_client):
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", "r6-concurrent", run_id="r6-concurrent")
    payload = {"code": "R6-RACE", "name": "R6 concurrent"}
    approval = _run(seeded_client, container.approvals.request_mutation("supplier_create", payload, ctx))
    _run(seeded_client, container.approvals.resolve_mutation(approval["approval_id"], "approve", "r6-race-decision", ctx))
    with _Simulator() as simulator:
        service = RemoteOperationService(container.mongo, container.clock, ErpClient(simulator.url),
                                         provider_scope=normalize_provider_scope(simulator.url),
                                         write_actions=frozenset({"supplier_create"}))

        async def race():
            return await asyncio.gather(
                service.execute(approval["approval_id"], "supplier_create", payload, "r6-race-key", ctx),
                service.execute(approval["approval_id"], "supplier_create", payload, "r6-race-key", ctx),
                return_exceptions=True)

        results = _run(seeded_client, race())
        assert sum(isinstance(value, dict) and value.get("status") == "succeeded" for value in results) == 1, repr(results)
        assert all(isinstance(value, (dict, AppError)) for value in results)
        assert len(simulator.posts) == 1


def test_remote_idempotency_scope_isolated_by_owner_and_provider(seeded_client):
    container = seeded_client.app.state.container
    first_ctx = RequestContext("owner-a", "r6-scope-a", run_id="r6-scope-a")
    second_ctx = RequestContext("owner-b", "r6-scope-b", run_id="r6-scope-b")
    payload = {"code": "R6-SCOPE", "name": "R6 scope"}

    def approved(ctx, decision_key):
        proposal = _run(seeded_client, container.approvals.request_mutation("supplier_create", payload, ctx))
        _run(seeded_client, container.approvals.resolve_mutation(
            proposal["approval_id"], "approve", decision_key, ctx))
        return proposal

    first_approval = approved(first_ctx, "r6-scope-decision-a")
    second_provider_approval = approved(first_ctx, "r6-scope-decision-provider-b")
    second_owner_approval = approved(second_ctx, "r6-scope-decision-owner-b")
    with _Simulator() as first_simulator, _Simulator() as second_simulator:
        first = RemoteOperationService(container.mongo, container.clock, ErpClient(first_simulator.url),
                                       provider_scope=normalize_provider_scope(first_simulator.url),
                                       write_actions=frozenset({"supplier_create"}))
        other_provider = RemoteOperationService(container.mongo, container.clock, ErpClient(second_simulator.url),
                                                provider_scope=normalize_provider_scope(second_simulator.url),
                                                write_actions=frozenset({"supplier_create"}))
        _run(seeded_client, first.execute(first_approval["approval_id"], "supplier_create", payload,
                                           "r6-scope-key", first_ctx))
        _run(seeded_client, other_provider.execute(second_provider_approval["approval_id"], "supplier_create", payload,
                                                   "r6-scope-key", first_ctx))
        _run(seeded_client, first.execute(second_owner_approval["approval_id"], "supplier_create", payload,
                                           "r6-scope-key", second_ctx))
        assert len(first_simulator.posts) == 2
        assert len(second_simulator.posts) == 1


def test_malformed_remote_response_is_persistently_unknown(seeded_client):
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", "r6-malformed", run_id="r6-malformed")
    payload = {"code": "R6-BAD", "name": "R6 malformed"}
    approval = _run(seeded_client, container.approvals.request_mutation("supplier_create", payload, ctx))
    _run(seeded_client, container.approvals.resolve_mutation(approval["approval_id"], "approve", "r6-bad-decision", ctx))
    with _Simulator() as simulator:
        # Persist an external effect but return a truncated body, which cannot be trusted.
        original = simulator.server.RequestHandlerClass.do_POST

        def malformed(handler):
            body = json.loads(handler.rfile.read(int(handler.headers["Content-Length"])))
            correlation = handler.headers["Idempotency-Key"]
            simulator.posts.append({"action": handler.path.lstrip("/"), "payload": body,
                                    "correlation_id": correlation})
            simulator.external[correlation] = {"id": "external-bad", "status": "accepted",
                                               "correlation_id": correlation}
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", "1")
            handler.end_headers()
            handler.wfile.write(b"{")

        simulator.server.RequestHandlerClass.do_POST = malformed
        try:
            service = RemoteOperationService(container.mongo, container.clock, ErpClient(simulator.url),
                                             provider_scope=normalize_provider_scope(simulator.url),
                                             write_actions=frozenset({"supplier_create"}))
            with pytest.raises(AppError) as unknown:
                _run(seeded_client, service.execute(approval["approval_id"], "supplier_create",
                                                    payload, "r6-bad-key", ctx))
            assert unknown.value.code == "OUTCOME_UNKNOWN"
            operation = _run(seeded_client, OperationRepository(container.mongo).get_remote_by_key(
                ctx.owner_id, service.provider_scope, "supplier_create", "r6-bad-key"))
            assert operation["status"] == "outcome_unknown"
            assert operation["dispatch_state"] == "dispatched"
            assert len(simulator.posts) == 1
        finally:
            simulator.server.RequestHandlerClass.do_POST = original


def test_result_save_failure_is_unknown_and_reconciles_without_repost(seeded_client, monkeypatch):
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", "r6-save-failure", run_id="r6-save-failure")
    payload = {"code": "R6-SAVE", "name": "R6 save failure"}
    approval = _run(seeded_client, container.approvals.request_mutation("supplier_create", payload, ctx))
    _run(seeded_client, container.approvals.resolve_mutation(approval["approval_id"], "approve", "r6-save-decision", ctx))
    with _Simulator() as simulator:
        scope = normalize_provider_scope(simulator.url)
        service = RemoteOperationService(container.mongo, container.clock, ErpClient(simulator.url),
                                         provider_scope=scope, write_actions=frozenset({"supplier_create"}))

        async def fail_persist(*_args, **_kwargs):
            raise RuntimeError("simulated Mongo result-save outage")

        monkeypatch.setattr(service.operations, "mark_remote_succeeded", fail_persist)
        with pytest.raises(AppError) as unknown:
            _run(seeded_client, service.execute(approval["approval_id"], "supplier_create",
                                                payload, "r6-save-key", ctx))
        assert unknown.value.code == "OUTCOME_UNKNOWN"
        assert len(simulator.posts) == 1
        operation = _run(seeded_client, OperationRepository(container.mongo).get_remote_by_key(
            ctx.owner_id, scope, "supplier_create", "r6-save-key"))
        assert operation["status"] == "outcome_unknown"

        reconciliation = ReconciliationService(OperationRepository(container.mongo), container.orders,
                                                container.clock, {scope: ErpClient(simulator.url)})
        result = _run(seeded_client, reconciliation.reconcile(operation["_id"], ctx))
        assert result["status"] == "succeeded"
        assert result["external_id"] == "external-1"
        assert len(simulator.posts) == 1


def test_remote_response_without_external_id_is_not_marked_succeeded(seeded_client):
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", "r6-no-remote-id", run_id="r6-no-remote-id")
    payload = {"code": "R6-NO-ID", "name": "R6 missing id"}
    approval = _run(seeded_client, container.approvals.request_mutation("supplier_create", payload, ctx))
    _run(seeded_client, container.approvals.resolve_mutation(approval["approval_id"], "approve", "r6-no-id-decision", ctx))
    with _Simulator() as simulator:
        simulator.omit_external_id = True
        service = RemoteOperationService(container.mongo, container.clock, ErpClient(simulator.url),
                                         provider_scope=normalize_provider_scope(simulator.url),
                                         write_actions=frozenset({"supplier_create"}))
        with pytest.raises(AppError) as unknown:
            _run(seeded_client, service.execute(approval["approval_id"], "supplier_create",
                                                payload, "r6-no-id-key", ctx))
        assert unknown.value.code == "OUTCOME_UNKNOWN"
        operation = _run(seeded_client, OperationRepository(container.mongo).get_remote_by_key(
            ctx.owner_id, service.provider_scope, "supplier_create", "r6-no-id-key"))
        assert operation["status"] == "outcome_unknown"
        assert operation.get("external_id") is None
        assert len(simulator.posts) == 1


def test_dispatch_marker_crash_never_dispatches_on_recovery(seeded_client):
    container = seeded_client.app.state.container
    ctx = RequestContext("local-owner", "r6-crash-window", run_id="r6-crash-window")
    payload = {"code": "R6-CRASH", "name": "R6 crash"}
    approval = _run(seeded_client, container.approvals.request_mutation("supplier_create", payload, ctx))
    _run(seeded_client, container.approvals.resolve_mutation(approval["approval_id"], "approve", "r6-crash-decision", ctx))
    with _Simulator() as simulator:
        scope = normalize_provider_scope(simulator.url)
        process_context = multiprocessing.get_context("spawn")
        process = process_context.Process(
            target=_crash_process_after_dispatch_marker,
            args=(container.settings.mongodb_uri.get_secret_value(), container.settings.mongodb_database,
                  simulator.url, approval["approval_id"], "r6-crash-key", ctx.owner_id))
        process.start()
        process.join(timeout=30)
        assert process.exitcode == 23
        operations = container.mongo.db.operations
        op = _run(seeded_client, operations.find_one({"owner_id": ctx.owner_id,
                                                      "provider_scope": scope,
                                                      "original_action": "supplier_create",
                                                      "idempotency_key": "r6-crash-key"}))
        assert op["dispatch_state"] == "dispatched"
        assert op["status"] == "outcome_unknown"
        recovered = RemoteOperationService(container.mongo, container.clock, ErpClient(simulator.url),
                                           provider_scope=scope, write_actions=frozenset({"supplier_create"}))
        with pytest.raises(AppError) as unknown:
            _run(seeded_client, recovered.execute(approval["approval_id"], "supplier_create",
                                                  payload, "r6-crash-key", ctx))
        assert unknown.value.code == "OUTCOME_UNKNOWN"
        reconciliation = ReconciliationService(OperationRepository(container.mongo), container.orders,
                                                container.clock, {scope: ErpClient(simulator.url)})
        result = _run(seeded_client, reconciliation.reconcile(op["_id"], ctx))
        assert result["status"] == "outcome_unknown"
        assert len(simulator.posts) == 0
