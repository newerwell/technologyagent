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

    class Orders:
        async def start_existing(self, run_id, message, ctx, budget, *, evidence_refs, parent_call_id, skill_context):
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
