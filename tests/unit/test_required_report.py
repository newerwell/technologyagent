from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.agent.budget import RunBudget
from backend.app.agent.graph import GraphExecutor
from backend.app.agent.graph_versions import route_executor
from backend.app.contracts.agent import ExecutorInput
from backend.app.contracts.agent import ExecutionOutcome
from backend.app.contracts.common import RequestContext
from backend.app.contracts.events import EventEnvelope
from backend.app.ports.tools import ToolResult


class _Runs:
    def __init__(self):
        self.items = []

    async def events(self, *_args):
        return list(self.items)

    async def append_event(self, run_id, kind, payload, ctx):
        self.items.append({"type": kind, "payload": payload})


class _Registry:
    def __init__(self, runs, *, register=True, verify=True):
        self.runs = runs
        self.register = register
        self.verify = verify
        self.calls = []
        self.verified = []

    def latest_report_dataset_id(self, ctx, _request_message=""):
        assert ctx.owner_id == "owner-a" and ctx.run_id == "run-a"
        return "dataset-1"

    def report_dataset_matches_request(self, dataset_id, ctx, request_message):
        assert dataset_id == "dataset-1" and ctx.owner_id == "owner-a"
        return True

    async def verify_report_artifact(self, artifact_id, dataset_id, report_format, ctx):
        self.verified.append((artifact_id, dataset_id, report_format, ctx.owner_id, ctx.run_id))
        if not self.verify:
            return None
        return {"artifact_id": artifact_id, "dataset_id": dataset_id, "format": report_format,
                "scope": "warehouse:W01", "source_refs": [{"entity": "inventory", "id": "I001"}],
                "content_sha256": "a" * 64}

    async def invoke(self, name, arguments, ctx, budget):
        self.calls.append((name, arguments, ctx.actor))
        if self.register:
            self.runs.items.append({"type": "artifact_ready", "payload": {"kind": arguments["format"], "artifact_id": "artifact-1",
                "source_refs": [{"entity": "inventory", "id": "I001"}], "purpose": "formal_report",
                "report_dataset_id": arguments["dataset_id"], "report_format": arguments["format"],
                "report_scope": "warehouse:W01", "content_sha256": "a" * 64}})
        return ToolResult(ok=True, data={"artifact_id": "artifact-1", "filename": f"report.{arguments['format']}",
                                         "kind": arguments["format"], "source_refs": [{"entity": "inventory", "id": "I001"}]})


class _Sink:
    def __init__(self):
        self.events = []

    async def emit(self, kind, payload):
        self.events.append((kind, payload))


def _request(message="分析W01补货并生成报告"):
    ctx = RequestContext(owner_id="owner-a", request_id="request-a", run_id="run-a", actor="analyst")
    return ExecutorInput(run_id="run-a", thread_id="thread-a", message=message,
                         ctx=ctx, graph_version="v2")


def test_required_report_is_created_and_registered_before_completion():
    runs = _Runs()
    registry = _Registry(runs)
    sink = _Sink()
    executor = GraphExecutor(None, lambda _ctx: None, runs=runs)

    result = asyncio.run(executor._generate_required_report(registry, _request(), sink, RunBudget("run-a")))

    assert result is True
    assert registry.calls == [("artifact_report", {"dataset_id": "dataset-1", "format": "md"}, "analyst")]
    assert [kind for kind, _ in sink.events] == ["tool_started", "tool_finished"]
    assert runs.items[0]["payload"]["artifact_id"] == "artifact-1"
    assert registry.verified == [("artifact-1", "dataset-1", "md", "owner-a", "run-a")]


def test_required_report_rejects_tool_success_without_registered_artifact_event():
    runs = _Runs()
    registry = _Registry(runs, register=False)
    sink = _Sink()
    executor = GraphExecutor(None, lambda _ctx: None, runs=runs)

    result = asyncio.run(executor._generate_required_report(registry, _request(), sink, RunBudget("run-a")))

    assert result is False
    assert [kind for kind, _ in sink.events] == ["tool_started", "tool_finished"]


def test_explicit_html_request_preserves_format_in_required_report_call():
    runs = _Runs()
    registry = _Registry(runs)
    executor = GraphExecutor(None, lambda _ctx: None, runs=runs)

    result = asyncio.run(executor._generate_required_report(registry, _request("分析W01全部库存并生成HTML报告"), _Sink(), RunBudget("run-a")))

    assert result is True
    assert registry.calls == [("artifact_report", {"dataset_id": "dataset-1", "format": "html"}, "analyst")]


def test_unrelated_existing_artifact_does_not_satisfy_required_report():
    runs = _Runs()
    runs.items.append({"type": "artifact_ready", "payload": {"kind": "json", "artifact_id": "debug-output"}})
    registry = _Registry(runs)
    executor = GraphExecutor(None, lambda _ctx: None, runs=runs)

    result = asyncio.run(executor._generate_required_report(registry, _request(), _Sink(), RunBudget("run-a")))

    assert result is True
    assert len(registry.calls) == 1
    assert registry.verified == [("artifact-1", "dataset-1", "md", "owner-a", "run-a")]


def test_report_with_unverified_formal_body_does_not_satisfy_requirement():
    runs = _Runs()
    registry = _Registry(runs, verify=False)
    executor = GraphExecutor(None, lambda _ctx: None, runs=runs)

    result = asyncio.run(executor._generate_required_report(registry, _request(), _Sink(), RunBudget("run-a")))

    assert result is False


@pytest.mark.parametrize("exception_name", ["RunCancelled", "RunDeadlineExceeded", "RunLimitExceeded"])
def test_required_report_preserves_budget_control_exceptions(exception_name):
    from backend.app.agent import budget as budget_module

    exception_type = getattr(budget_module, exception_name)
    runs = _Runs()

    class ControlRegistry(_Registry):
        async def invoke(self, *_args):
            raise exception_type(exception_name)

    executor = GraphExecutor(None, lambda _ctx: None, runs=runs)
    with pytest.raises(exception_type):
        asyncio.run(executor._generate_required_report(ControlRegistry(runs, register=False), _request(), _Sink(), RunBudget("run-a")))


def test_parent_routes_to_order_only_after_persisted_report_ready_event():
    calls = []

    class Runs(_Runs):
        async def record_skill_manifest(self, *_args): pass
        async def record_specialist(self, *_args, **_kwargs): pass

        async def events(self, *_args):
            return [EventEnvelope(
                type="report_verified", event_id="event-1", seq=1, thread_id="thread-a",
                run_id="run-a", at=datetime.now(timezone.utc),
                payload={"format": "md", "artifact_id": "artifact-1", "dataset_id": "dataset-1",
                         "scope": "warehouse:W01", "source_refs": [{"entity": "inventory", "id": "I001"}],
                         "content_sha256": "a" * 64},
            )]

    class Orders:
        async def start_existing(self, *_args, **_kwargs):
            calls.append("order_prepare")
            return SimpleNamespace(status="waiting_input", summary="approval", pending_interrupt=None,
                                   error_code=None, committed_facts=False)

    class Executor:
        _runs = Runs()
        _order_workflows = Orders()

        async def _execute_graph(self, request, _sink, _budget):
            assert request.ctx.actor == "analyst"
            assert "\u62a5\u544a" in request.message
            calls.append("analyst_completed")
            return ExecutionOutcome(status="completed", summary="report generated", evidence=[])

    message = ("\u5206\u6790 W01 \u7684 P001 \u8865\u8d27\u9700\u6c42\u5e76\u751f\u6210\u62a5\u544a\uff0c"
               "\u7136\u540e\u51c6\u5907 P001 \u5728 W01 \u7684\u8ba2\u5355\uff0c7\u5929\u5185\u5230\u8d27\u3002")
    request = ExecutorInput(run_id="run-a", thread_id="thread-a", message=message,
        ctx=RequestContext(owner_id="owner-a", request_id="request-a", run_id="run-a"), graph_version="v2")
    outcome = asyncio.run(route_executor(Executor(), request, _Sink(), RunBudget("run-a")))

    assert outcome.status == "waiting_input"
    assert calls == ["analyst_completed", "order_prepare"]


def test_parent_does_not_start_order_after_unrelated_artifact_event():
    calls = []

    class Runs(_Runs):
        async def record_skill_manifest(self, *_args): pass
        async def record_specialist(self, *_args, **_kwargs): pass

        async def events(self, *_args):
            return [EventEnvelope(type="artifact_ready", event_id="event-1", seq=1, thread_id="thread-a",
                run_id="run-a", at=datetime.now(timezone.utc),
                payload={"kind": "json", "artifact_id": "unrelated", "filename": "debug.json", "source_refs": []})]

    class Orders:
        async def start_existing(self, *_args, **_kwargs):
            calls.append("order_prepare")
            return SimpleNamespace(status="waiting_input", summary="approval", pending_interrupt=None,
                                   error_code=None, committed_facts=False)

    class Executor:
        _runs = Runs()
        _order_workflows = Orders()

        async def _execute_graph(self, *_args):
            calls.append("analyst_completed")
            return ExecutionOutcome(status="completed", summary="reported", evidence=[])

    message = "分析W01库存并生成HTML报告，然后准备W01订单。"
    request = ExecutorInput(run_id="run-a", thread_id="thread-a", message=message,
        ctx=RequestContext(owner_id="owner-a", request_id="request-a", run_id="run-a"), graph_version="v2")
    outcome = asyncio.run(route_executor(Executor(), request, _Sink(), RunBudget("run-a")))

    assert outcome.status == "failed"
    assert outcome.error_code == "REPORT_ARTIFACT_REQUIRED"
    assert calls == ["analyst_completed"]
