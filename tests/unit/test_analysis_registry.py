import pytest

from backend.app.agent.budget import RunBudget
from backend.app.agent.tools.analysis import AnalysisRegistryFactory, AnalysisToolRegistry
from backend.app.contracts.common import RequestContext
from backend.app.ports.tools import ToolResult, ToolSpec


class BaseRegistry:
    def __init__(self): self.calls = []
    def available(self, ctx): return [ToolSpec(name="inventory_page", description="read", input_schema={})]
    async def invoke(self, name, arguments, ctx, budget):
        self.calls.append(name)
        return ToolResult(ok=True, data={"records": [{"id": "I001", "on_hand": 20}]}, meta={"data_source": "local_seed"})


class UnavailableSandbox:
    def __init__(self): self.executed = False
    async def available(self): return False, "daemon unavailable"
    async def execute(self, job, ctx): self.executed = True; raise AssertionError("must not execute")


class NoArtifacts:
    async def open(self, artifact_id, ctx): raise AssertionError("untrusted ID must not reach storage")
    async def register(self, output, ctx): raise AssertionError("sandbox did not run")


class NoEvents:
    async def append_event(self, *args): raise AssertionError("sandbox did not run")


@pytest.mark.asyncio
async def test_docker_failure_preserves_read_tools_and_never_falls_back_to_host():
    base, sandbox = BaseRegistry(), UnavailableSandbox()
    registry = AnalysisToolRegistry(base, sandbox, NoArtifacts(), NoEvents(), sandbox_enabled=False)
    ctx = RequestContext(owner_id="owner-a", request_id="req", run_id="run-a")
    budget = RunBudget("run-a")
    assert [tool.name for tool in registry.available(ctx)] == ["inventory_page"]
    read = await registry.invoke("inventory_page", {}, ctx, budget)
    assert read.ok and read.data["records"][0]["on_hand"] == 20
    dataset_id = read.meta["dataset_id"]
    failure = await registry.invoke("analysis_execute", {
        "code": "open('/etc/passwd').read()", "input_dataset_ids": [dataset_id], "output_allowlist": ["out.csv"],
    }, ctx, budget)
    assert not failure.ok and failure.error["code"] == "SANDBOX_UNAVAILABLE"
    assert base.calls == ["inventory_page"] and not sandbox.executed


@pytest.mark.asyncio
async def test_forged_dataset_id_is_rejected_before_execution():
    class AvailableSandbox(UnavailableSandbox):
        async def available(self): return True, "ready"
    sandbox = AvailableSandbox()
    registry = AnalysisToolRegistry(BaseRegistry(), sandbox, NoArtifacts(), NoEvents())
    ctx = RequestContext(owner_id="owner-a", request_id="req", run_id="run-a")
    result = await registry.invoke("analysis_execute", {
        "code": "pass", "input_dataset_ids": ["ds_not-from-this-run"], "output_allowlist": ["report.csv"],
    }, ctx, RunBudget("run-a"))
    assert not result.ok and result.error["code"] == "ANALYSIS_FAILED"
    assert not sandbox.executed


@pytest.mark.asyncio
async def test_factory_hides_analysis_tool_when_docker_is_unavailable():
    base, sandbox = BaseRegistry(), UnavailableSandbox()

    async def make_base(_ctx):
        return base

    registry = await AnalysisRegistryFactory(make_base, sandbox, NoArtifacts(), NoEvents())(
        RequestContext(owner_id="owner-a", request_id="req", run_id="run-a"))
    assert [tool.name for tool in registry.available(RequestContext(owner_id="owner-a", request_id="req", run_id="run-a"))] == [
        "inventory_page",
    ]
