from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.agent.budget import RunBudget
from backend.app.agent.graph import SYSTEM_PROMPT
from backend.app.agent.prompt_layout import build_v2_initial_messages, messages_with_verified_facts
from backend.app.contracts.agent import ExecutorInput, ModelDelta, ModelMessage, ModelToolCall
from backend.app.contracts.common import RequestContext


def _request(message: str, *, actor: str = "main", skill_context: str = "", constraints=None):
    ctx = RequestContext(owner_id="owner", request_id="request", run_id="run", actor=actor)
    return ExecutorInput(
        run_id="run", thread_id="thread", message=message, ctx=ctx,
        graph_version="v2", skill_context=skill_context,
    ), constraints or {}


def test_v2_static_prefix_is_identical_for_same_analyst_report_skill_variant():
    first, first_scope = _request(
        "分析P001并生成报告", actor="analyst", skill_context="## procurement-report@1.0.0\n固定技能",
        constraints={"warehouse_ids": ["W01"], "max_lead_days": 7},
    )
    second, second_scope = _request(
        "分析P002并生成报告", actor="analyst", skill_context="## procurement-report@1.0.0\n固定技能",
        constraints={"warehouse_ids": ["W02"], "max_lead_days": 7},
    )

    first_messages, first_template = build_v2_initial_messages(first, first_scope)
    second_messages, second_template = build_v2_initial_messages(second, second_scope)

    assert first_template == second_template == "ta-v2-base-1:analyst_report"
    assert first_messages[0] == second_messages[0] == ModelMessage(role="system", content=SYSTEM_PROMPT)
    assert first_messages[1] == second_messages[1]
    assert first_messages[1].role == "system"
    assert "artifact_report" in first_messages[1].content
    assert "固定技能" in first_messages[1].content
    assert first_messages[2].role == second_messages[2].role == "system"
    assert '"warehouse_ids": ["W01"]' in first_messages[2].content
    assert '"warehouse_ids": ["W02"]' in second_messages[2].content
    assert first_messages[2].content != second_messages[2].content
    assert first_messages[-1].content == "分析P001并生成报告"
    assert second_messages[-1].content == "分析P002并生成报告"


def test_v2_report_and_non_report_templates_differ_and_empty_blocks_are_omitted():
    report, report_scope = _request("分析P001并生成报告", actor="analyst")
    ordinary, ordinary_scope = _request("分析P001", actor="analyst")
    main, main_scope = _request("你好")

    report_messages, report_template = build_v2_initial_messages(report, report_scope)
    ordinary_messages, ordinary_template = build_v2_initial_messages(ordinary, ordinary_scope)
    main_messages, _ = build_v2_initial_messages(main, main_scope)

    assert report_template == "ta-v2-base-1:analyst_report"
    assert ordinary_template == "ta-v2-base-1:analyst"
    assert report_template != ordinary_template
    assert "artifact_report" in report_messages[1].content
    assert "artifact_report" not in ordinary_messages[1].content
    assert [message.role for message in main_messages] == ["system", "user"]
    assert all(message.content for message in main_messages)


def test_verified_facts_are_added_as_trusted_system_without_mutating_existing_messages():
    request, scope = _request(
        "比较P001报价", actor="analyst", skill_context="## supplier-comparison@1.0.0\n固定技能",
        constraints={"supplier_id": "S02", "max_lead_days": 5},
    )
    initial, _template = build_v2_initial_messages(request, scope)
    assistant = ModelMessage(
        role="assistant", content="", tool_calls=[ModelToolCall(id="call-1", name="quote_list")]
    )
    tool = ModelMessage(role="tool", name="quote_list", tool_call_id="call-1", content='{"ok":true}')
    conversation = [*initial, assistant, tool]
    original = list(conversation)

    with_facts = messages_with_verified_facts(conversation, "P001最低有效报价为12.50元。")

    assert conversation == original
    assert with_facts[:2] == initial[:2]
    assert with_facts[2] == initial[2]
    assert with_facts[3].role == "system"
    assert "P001最低有效报价为12.50元。" in with_facts[3].content
    assert "不得替换你的回答" in with_facts[3].content
    assert with_facts[4:] == conversation[3:]
    assert any("supplier_id" in message.content and '"S02"' in message.content for message in with_facts)
    assert any(message.role == "user" and message.content == request.message for message in with_facts)
    assert with_facts[-2:] == [assistant, tool]


@pytest.mark.asyncio
async def test_v2_model_node_uses_new_layout_only_when_template_id_exists(monkeypatch):
    pytest.importorskip("pymongo")
    import backend.app.agent.versions.v2_impl as v2_impl

    observations = []

    class Registry:
        def available(self, _ctx):
            return []

    class Sink:
        async def emit(self, *_args, **_kwargs):
            return None

    async def collect(_model, messages, _tools, _ctx, _budget, _emit, **kwargs):
        observations.append((list(messages), kwargs))
        return SimpleNamespace(
            deltas=[ModelDelta(kind="token", content="已完成查询。")],
            usage=None,
            successful_call_id="model-call",
        )

    monkeypatch.setattr(v2_impl, "render_verified_core_facts", lambda _state: "完整核验事实。")
    monkeypatch.setattr(v2_impl, "collect_model_response", collect)
    request, scope = _request("分析P001", actor="analyst", skill_context="固定技能",
                              constraints={"warehouse_ids": ["W01"]})
    initial, template_id = build_v2_initial_messages(request, scope)

    for marker in (template_id, None):
        graph = v2_impl.build_graph_v2(
            object(), Registry(), Sink(), RunBudget("run"), request.ctx,
        )
        await graph.ainvoke({
            "messages": list(initial),
            "pending_tool_calls": [],
            "evidence": [],
            **({"prompt_template_id": marker} if marker else {}),
        })

    new_messages, new_kwargs = observations[0]
    assert new_kwargs["prompt_template_id"] == template_id
    assert new_messages[0].content == SYSTEM_PROMPT
    assert new_messages[1].content == "固定技能"
    assert "完整核验事实。" in new_messages[3].content
    assert new_messages[4].content == request.message

    legacy_messages, legacy_kwargs = observations[1]
    assert legacy_kwargs["prompt_template_id"] is None
    assert "完整核验事实。" in legacy_messages[0].content
    assert legacy_messages[0].content.startswith(SYSTEM_PROMPT)
