from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import backend.app.agent.graph as graph_module
import backend.app.agent.versions.v1_impl as v1_impl
import backend.app.agent.versions.v2 as v2_module
import backend.app.services.order_workflows as order_workflows_module
from backend.app.agent.budget import RunBudget
from backend.app.contracts.agent import ExecutorInput, ModelDelta
from backend.app.contracts.common import RequestContext
from backend.app.contracts.workflow import ReviewResult
from backend.app.services.order_workflows import OrderWorkflowService


FIXTURE = Path(__file__).parents[1] / "fixtures" / "p07-v1-pending-approval.json"
FIXTURE_SHA256 = "1fd530124549641fd790a9e8a730db51e2c2b14dab6aa894f501e1dbb950a318"


class _Sink:
    async def emit(self, *_args, **_kwargs):
        return None


class _Registry:
    def available(self, _ctx):
        return []

    async def invoke(self, *_args, **_kwargs):
        raise AssertionError("no tools expected")


class _Model:
    async def stream(self, *_args):
        yield ModelDelta(kind="token", content="已完成只读查询。")


@pytest.mark.asyncio
async def test_preupgrade_v1_graph_runs_even_if_mutable_graph_module_builder_changes(monkeypatch):
    def changed_builder(*_args, **_kwargs):
        raise AssertionError("simulated v2 graph builder replacement")

    monkeypatch.setattr(graph_module, "build_graph_v1", changed_builder)
    passing_review = lambda _state: ReviewResult(passed=True, checks=[])
    async def passing_semantic_review(_state, *_args, **_kwargs):
        return ReviewResult(passed=True, checks=[])
    monkeypatch.setattr(graph_module, "deterministic_review", passing_review)
    monkeypatch.setattr(graph_module, "semantic_review", passing_semantic_review)
    monkeypatch.setattr(v1_impl, "deterministic_review", passing_review)
    ctx = RequestContext(owner_id="owner", request_id="request", run_id="run")
    request = ExecutorInput(run_id="run", thread_id="thread", message="查询库存", ctx=ctx, graph_version="v1")
    async def registry_factory(_ctx):
        return _Registry()

    executor = graph_module.GraphExecutor(_Model(), registry_factory, model_mode="fake")

    outcome = await executor.execute(request, _Sink(), RunBudget("run"))

    assert outcome.status == "completed", outcome
    assert outcome.summary == "已完成只读查询。"


def test_historical_pending_approval_fixture_bytes_remain_pinned():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA256


def test_v1_order_graph_does_not_call_v2_order_builder(monkeypatch):
    service = object.__new__(OrderWorkflowService)
    service._drafts = object()
    service._approvals = object()
    service._mutations = object()
    service._mongo = type("Mongo", (), {"checkpointer": None})()
    service._runs = object()

    def changed_builder(*_args, **_kwargs):
        raise AssertionError("simulated shared v2 workflow mutation")

    monkeypatch.setattr(order_workflows_module, "V2_ORDER_GRAPH_BUILDER", changed_builder)
    assert service._graph("v1") is not None


def test_v1_and_v2_export_independent_graph_and_order_builders():
    import backend.app.agent.versions.v1 as v1_module

    assert v1_module.V1_GRAPH_BUILDER is not v2_module.V2_GRAPH_BUILDER
    assert v1_module.V1_ORDER_GRAPH_BUILDER is not v2_module.V2_ORDER_GRAPH_BUILDER
