from pathlib import Path

import pytest
import asyncio
import shutil
from types import SimpleNamespace

from backend.app.agent.skill_loader import load_skill, select_skills
from backend.app.agent.specialists.policy import RoleToolRegistry, load_specialists
from backend.app.agent.specialists.dispatcher import SpecialistDispatcher
from backend.app.agent.deepagent_adapter import assert_locked_compatibility
from backend.app.agent.budget import RunBudget
from backend.app.contracts.agent import ExecutionOutcome
from backend.app.contracts.agent import ExecutorInput
from backend.app.contracts.common import RequestContext
from backend.app.ports.tools import ToolResult, ToolSpec
from backend.app.agent.graph_versions import route_executor
from backend.app.contracts.agent import ExecutorInput


class FakeRegistry:
    def __init__(self):
        self.calls = []

    def available(self, _ctx):
        return [ToolSpec(name=name, description="", input_schema={}) for name in
                ("inventory_page", "analysis_execute", "order_create", "order_page")]

    async def invoke(self, name, arguments, ctx, budget):
        self.calls.append((name, ctx.actor))
        return ToolResult(ok=True, data={"ok": True})


def test_specialist_declarations_and_runtime_registry_enforce_both_directions():
    specs = load_specialists()
    assert "analysis_execute" in specs["analyst"].tools
    assert "analysis_execute" not in specs["order"].tools
    assert "order_create" not in specs["analyst"].tools
    assert all(spec.can_approve is False and spec.recursive_delegation is False for spec in specs.values())
    for spec in specs.values():
        assert spec.input_schema["properties"]["task"]["type"] == "string"
        assert spec.output_schema["properties"]["evidence_refs"]["items"]["type"] == "object"

    base = FakeRegistry()
    analyst = RoleToolRegistry(base, "analyst", specs["analyst"].tools)
    ctx = RequestContext(owner_id="owner-a", request_id="r", actor="analyst")
    assert {spec.name for spec in analyst.available(ctx)} == {"inventory_page", "analysis_execute"}

    budget = RunBudget("r")
    denied = asyncio.run(analyst.invoke("order_create", {}, ctx, budget))
    assert denied.ok is False and denied.error["code"] == "ACTOR_FORBIDDEN"
    main = RoleToolRegistry(base, "main", {"inventory_page"})
    denied_analysis = asyncio.run(main.invoke("analysis_execute", {}, RequestContext(owner_id="o", request_id="r"), budget))
    assert denied_analysis.ok is False and denied_analysis.error["code"] == "ACTOR_FORBIDDEN"
    order = RoleToolRegistry(base, "order", specs["order"].tools)
    denied_order = asyncio.run(order.invoke("analysis_execute", {}, RequestContext(owner_id="o", request_id="r", actor="order"), budget))
    assert denied_order.ok is False and denied_order.error["code"] == "ACTOR_FORBIDDEN"
    assert base.calls == []


def test_dispatcher_rejects_recursion_caps_calls_and_shares_parent_budget():
    dispatcher = SpecialistDispatcher(max_delegations=2)
    budget = RunBudget("parent")
    received = []

    async def invoke(request):
        received.append((request.owner_id, request.run_id, budget))
        return ExecutionOutcome(status="completed", summary="analyst result")

    async def scenario():
        first = await dispatcher.dispatch(owner_id="owner-a", run_id="parent", specialist="analyst",
            task="analyze", data_scope={"warehouse_id": "W01"}, evidence_refs=[], preferences={},
            parent_call_id="call-1", budget=budget, invoke=invoke)
        second = await dispatcher.dispatch(owner_id="owner-a", run_id="parent", specialist="order",
            task="prepare", data_scope={}, evidence_refs=[], preferences={},
            parent_call_id="call-2", budget=budget, invoke=invoke)
        overflow = await dispatcher.dispatch(owner_id="owner-a", run_id="parent", specialist="order",
            task="prepare", data_scope={}, evidence_refs=[], preferences={},
            parent_call_id="call-3", budget=budget, invoke=invoke)
        recursive = await dispatcher.dispatch(owner_id="owner-a", run_id="parent", specialist="analyst",
            task="again", data_scope={}, evidence_refs=[], preferences={},
            parent_call_id="call-4", budget=budget, invoke=invoke, recursive=True)
        return first, second, overflow, recursive

    first, second, overflow, recursive = asyncio.run(scenario())
    assert first.status == second.status == "completed"
    assert overflow.error_code == "DELEGATION_LIMIT"
    assert recursive.error_code == "DELEGATION_RECURSION"
    assert received == [("owner-a", "parent", budget), ("owner-a", "parent", budget)]


def test_combined_request_passes_structured_analyst_evidence_to_order_specialist():
    evidence = [{"entity": "inventory", "id": "I001", "field": "shortage", "value": 55}]
    seen = {}

    class Runs:
        async def record_skill_manifest(self, *_args):
            return None

        async def record_specialist(self, *_args, **_kwargs):
            return None

        async def events(self, *_args):
            return [SimpleNamespace(type="report_verified", payload={
                "artifact_id": "artifact-verified",
                "dataset_id": "dataset-verified",
                "format": "md",
                "scope": "warehouse=W01",
                "source_refs": [{"tool_call_id": "call-1", "record_id": "I001"}],
                "content_sha256": "a" * 64,
            })]

    class Orders:
        async def start_existing(self, run_id, message, ctx, budget, *, evidence_refs, parent_call_id, skill_context,
                                 preference_overrides=None, request_constraints=None):
            seen.update(run_id=run_id, message=message, evidence_refs=evidence_refs,
                        parent_call_id=parent_call_id, skill_context=skill_context)
            interrupt = SimpleNamespace(model_dump=lambda mode: {"kind": "approval"})
            return SimpleNamespace(status="waiting_input", summary="需要人工确认", pending_interrupt=interrupt,
                                   error_code=None, committed_facts=False)

    class Executor:
        _runs = Runs()
        _order_workflows = Orders()

        async def _execute_graph(self, child, _sink, _budget):
            assert child.ctx.actor == "analyst"
            assert "inventory-replenishment" in child.skill_context
            assert child.request_constraints["max_lead_days"] == 7
            return ExecutionOutcome(status="completed", summary="缺口55件", evidence=evidence)

    ctx = RequestContext(owner_id="owner-a", request_id="request-a", run_id="run-a")
    request = ExecutorInput(run_id="run-a", thread_id="thread-a",
        message="分析 W01 的 P001 补货需求并生成报告，然后准备 P001 在 W01 的订单，7天内到货。",
        ctx=ctx, graph_version="v2")
    outcome = asyncio.run(route_executor(Executor(), request, object(), RunBudget("run-a")))
    assert outcome.status == "waiting_input"
    assert seen["evidence_refs"] == evidence
    assert seen["run_id"] == "run-a" and seen["parent_call_id"]
    assert "inventory-replenishment" in seen["skill_context"]


def test_deepagents_lock_is_checked_and_unsafe_builtins_are_documented():
    report = assert_locked_compatibility()
    assert report["deepagents_version"] == "0.7.30"
    assert report["accepts_modelport"] is False
    assert report["built_in_tools_default"] is True
    assert report["adapter"] == "explicit_langgraph_subgraphs"


def test_v1_checkpoint_abi_is_pinned_independently_of_v2_adapter():
    from backend.app.agent import graph_versions
    from backend.app.agent.versions import v1, v2

    builder = v1.V1_GRAPH_BUILDER
    state = v1.V1_STATE_SCHEMA
    abi = dict(v1.CHECKPOINT_ABI)
    assert abi["graph_version"] == "v1"
    assert abi["order_namespace"] == "run_id"
    assert v1.V1_WORKFLOW_CONFIG("thread", "run", "v1")["configurable"]["checkpoint_ns"] == "run"
    assert callable(v2.build_specialist_subgraph)
    assert v1.V1_GRAPH_BUILDER is builder and v1.V1_STATE_SCHEMA is state and dict(v1.CHECKPOINT_ABI) == abi


def test_specialist_system_prompt_includes_parent_request_constraints():
    from backend.app.agent.graph import build_specialist_system_prompt
    request = ExecutorInput(run_id="run-a", thread_id="thread-a", message="分析 P001 补货并生成报告",
        ctx=RequestContext(owner_id="owner-a", request_id="request-a", run_id="run-a", actor="analyst"),
        graph_version="v2", skill_context="采购报告指引",
        request_constraints={"warehouse_ids": ["W01"], "part_ids": ["P001"], "max_lead_days": 7,
                             "intent": "supplier_recommendation"})
    prompt = build_specialist_system_prompt(request)
    assert "max_lead_days" in prompt and '"max_lead_days": 7' in prompt
    assert "采购报告指引" in prompt


def test_report_request_requires_file_artifact_instruction():
    from backend.app.agent.graph import build_specialist_system_prompt

    request = ExecutorInput(run_id="run-a", thread_id="thread-a", message="分析 P001 并生成采购报告",
        ctx=RequestContext(owner_id="owner-a", request_id="request-a", run_id="run-a", actor="analyst"),
        graph_version="v2", skill_context="采购报告技能")
    prompt = build_specialist_system_prompt(request)
    assert "必须调用 artifact_report" in prompt
    assert "不能用文本摘要代替文件" in prompt


def test_report_then_order_stops_before_order_if_report_artifact_is_missing():
    class Runs:
        async def record_skill_manifest(self, *_args): pass
        async def record_specialist(self, *_args, **_kwargs): pass
        async def events(self, *_args): return []

    class Orders:
        def __init__(self): self.calls = 0
        async def start_existing(self, *_args, **_kwargs):
            self.calls += 1
            return SimpleNamespace(status="waiting_input", summary="approval", pending_interrupt=None,
                                   error_code=None, committed_facts=False)

    orders = Orders()
    class Executor:
        _runs = Runs()
        _order_workflows = orders
        async def _execute_graph(self, *_args):
            return ExecutionOutcome(status="completed", summary="分析已完成，但没有报告文件。")

    request = ExecutorInput(run_id="run-a", thread_id="thread-a",
        message="分析 W01 的 P001 补货需求并生成报告，然后准备 P001 在 W01 的订单，7天内到货。",
        ctx=RequestContext(owner_id="owner-a", request_id="r", run_id="run-a"), graph_version="v2")
    outcome = asyncio.run(route_executor(Executor(), request, object(), RunBudget("run-a")))
    assert outcome.status == "failed" and outcome.error_code == "REPORT_ARTIFACT_REQUIRED"
    assert orders.calls == 0


def test_order_only_and_read_only_order_query_take_distinct_paths():
    calls = []

    class Runs:
        async def record_skill_manifest(self, *_args): pass
        async def record_specialist(self, *_args, **_kwargs): pass

    class Orders:
        async def start_existing(self, *_args, **_kwargs):
            calls.append("prepare")
            return SimpleNamespace(status="waiting_input", summary="approval", pending_interrupt=None,
                                   error_code=None, committed_facts=False)

    class Executor:
        _runs = Runs()
        _order_workflows = Orders()
        async def _execute_graph(self, request, _sink, _budget):
            calls.append((request.ctx.actor, request.message))
            return ExecutionOutcome(status="completed", summary="查询完成")

    ctx = RequestContext(owner_id="owner-a", request_id="r", run_id="run-a")
    prepare = ExecutorInput(run_id="run-a", thread_id="t", message="准备 P001 在 W01 的订单，7天内到货。",
                            ctx=ctx, graph_version="v2")
    query = ExecutorInput(run_id="run-a", thread_id="t", message="查询已经提交订单的状态。",
                          ctx=ctx, graph_version="v2")
    assert asyncio.run(route_executor(Executor(), prepare, object(), RunBudget("run-a"))).status == "waiting_input"
    assert asyncio.run(route_executor(Executor(), query, object(), RunBudget("run-a"))).status == "completed"
    assert "prepare" in calls
    assert ("order", "查询已经提交订单的状态。") in calls


def test_chat_preference_command_is_explicit_and_report_skill_union_is_minimal():
    from backend.app.agent.skill_loader import select_skills_for_request

    class Preferences:
        KEYS = {"default_warehouse", "preferred_supplier", "max_lead_days"}
        def __init__(self): self.saved = {}
        async def remember(self, owner, request): self.saved[request.key] = (owner, request.value)
        async def list(self, owner): return {key: value for key, (saved_owner, value) in self.saved.items() if saved_owner == owner}
        async def delete(self, owner, key): return self.saved.pop(key, None) is not None

    prefs = Preferences()
    class Executor:
        _preferences = prefs
        async def _execute_graph(self, *_args): raise AssertionError("preference command must not call model")

    ctx = RequestContext(owner_id="owner-a", request_id="r", run_id="run-a")
    request = ExecutorInput(run_id="run-a", thread_id="t", message="记住默认仓库W02", ctx=ctx, graph_version="v2")
    outcome = asyncio.run(route_executor(Executor(), request, object(), RunBudget("run-a")))
    assert outcome.status == "completed"
    assert prefs.saved == {"default_warehouse": ("owner-a", "W02")}
    standalone = {item.id for item in select_skills_for_request("生成W01采购报告", "analyst")}
    combined = {item.id for item in select_skills_for_request("查看W01库存并生成采购报告", "analyst")}
    assert standalone == {"procurement-report"}
    assert combined == {"inventory-replenishment", "procurement-report"}


def test_order_intent_cancellation_is_not_swallowed_as_specialist_failure():
    from backend.app.agent.budget import RunCancelled

    class Runs:
        async def record_skill_manifest(self, *_args): pass
        async def record_specialist(self, *_args, **_kwargs): pass
    class Orders:
        async def start_existing(self, *_args, **_kwargs): raise RunCancelled("run-a")
    class Executor:
        _runs = Runs()
        _order_workflows = Orders()
        async def _execute_graph(self, *_args): raise AssertionError("no analyst task expected")

    ctx = RequestContext(owner_id="owner-a", request_id="r", run_id="run-a")
    request = ExecutorInput(run_id="run-a", thread_id="t", message="准备 P001 在 W01 的订单，7天内到货。",
                            ctx=ctx, graph_version="v2")
    with pytest.raises(RunCancelled):
        asyncio.run(route_executor(Executor(), request, object(), RunBudget("run-a")))


def test_saved_preference_reaches_analysis_scope_and_current_turn_wins():
    seen = []
    class Preferences:
        async def list(self, owner):
            assert owner == "owner-a"
            return {"default_warehouse": "W02", "preferred_supplier": "S01", "max_lead_days": 7}
    class Runs:
        async def record_skill_manifest(self, *_args): pass
        async def record_specialist(self, *_args, **_kwargs): pass
    class Executor:
        _preferences = Preferences()
        _runs = Runs()
        async def _execute_graph(self, request, _sink, _budget):
            seen.append((request.ctx.actor, request.request_constraints))
            return ExecutionOutcome(status="completed", summary="读取完毕")

    ctx = RequestContext(owner_id="owner-a", request_id="r", run_id="run-a")
    for message, expected in (("P001库存缺口是多少？", ["W02"]), ("本轮只查W01的P001库存", ["W01"])):
        request = ExecutorInput(run_id="run-a", thread_id="t", message=message, ctx=ctx, graph_version="v2")
        result = asyncio.run(route_executor(Executor(), request, object(), RunBudget("run-a")))
        assert result.status == "completed"
        assert seen[-1][0] == "analyst"
        assert seen[-1][1]["warehouse_ids"] == expected
    assert seen[-1][1]["preference_sources"]["default_warehouse"] == "explicit_request"


def test_specialist_schema_rejects_non_json_schema_properties(tmp_path: Path):
    source = Path(__file__).parents[2] / "backend" / "app" / "agent" / "specialists"
    shutil.copytree(source, tmp_path / "specialists")
    analyst = tmp_path / "specialists" / "analyst.yaml"
    analyst.write_text(analyst.read_text(encoding="utf-8").replace(
        "task: {type: string, minLength: 1, maxLength: 2000}", "task: string"
    ), encoding="utf-8")
    # Schema fields must themselves be valid schema objects, not shorthand strings.
    with pytest.raises(ValueError, match="schemas"):
        load_specialists(tmp_path / "specialists")


def test_skill_selection_is_task_specific_and_content_hash_tracks_edits(tmp_path: Path):
    root = tmp_path / "skills"
    skill = root / "inventory-replenishment"
    (skill / "examples").mkdir(parents=True)
    file = skill / "SKILL.md"
    file.write_text("---\nid: inventory-replenishment\nversion: 1.0.0\n---\nUse inventory facts.\n", encoding="utf-8")
    example = skill / "examples" / "sample.md"
    example.write_text("Example: query by warehouse.", encoding="utf-8")

    loaded = load_skill("inventory-replenishment", root)
    assert loaded.version == "1.0.0" and loaded.examples
    before = loaded.content_hash
    file.write_text(file.read_text(encoding="utf-8") + "Only report verified facts.\n", encoding="utf-8")
    assert load_skill("inventory-replenishment", root).content_hash != before
    assert [item.id for item in select_skills("inventory", "analyst", root)] == ["inventory-replenishment"]
    assert "Use inventory facts." in load_skill("inventory-replenishment", root).instructions
    assert select_skills("unknown", "main", root) == ()
    with pytest.raises(ValueError):
        load_skill("../outside", root)
