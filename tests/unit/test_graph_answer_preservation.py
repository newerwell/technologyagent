from __future__ import annotations

import pytest

import backend.app.agent.graph as graph_module
from backend.app.agent.budget import RunBudget
from backend.app.contracts.agent import ExecutorInput, ModelDelta
from backend.app.contracts.common import RequestContext
from backend.app.contracts.workflow import ReviewCheck, ReviewResult


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, kind: str, payload: dict) -> None:
        self.events.append((kind, payload))


class EmptyRegistry:
    def available(self, _ctx):
        return []

    async def invoke(self, *_args, **_kwargs):
        raise AssertionError("no tools are expected in this regression")


class RevisedAnswerModel:
    def __init__(self) -> None:
        self.calls: list[list] = []

    async def stream(self, messages, _tools, _ctx):
        self.calls.append(list(messages))
        answer = "P003没有有效报价。"
        if len(self.calls) > 1:
            answer = "P003没有有效报价；原因是报价已过期。"
        yield ModelDelta(kind="token", content=answer)


@pytest.mark.asyncio
async def test_semantic_revision_keeps_model_answer_and_uses_verified_facts_only_in_copy(monkeypatch):
    import backend.app.agent.graph as graph

    monkeypatch.setattr(graph, "classify_task", lambda _message: "general")
    monkeypatch.setattr(graph, "build_plan", lambda _task_type: [])
    monkeypatch.setattr(graph, "render_verified_core_facts", lambda _state: "核验辅助事实：报价已过期。")
    monkeypatch.setattr(graph, "deterministic_review", lambda _state: ReviewResult(
        passed=True, checks=[ReviewCheck(check_id="HARD", passed=True)]
    ))
    semantic_answers: list[str] = []

    async def review(state, *_args, **_kwargs):
        answer = state["final_answer"]
        semantic_answers.append(answer)
        if "原因是报价已过期" not in answer:
            return ReviewResult(passed=False, checks=[ReviewCheck(
                check_id="SEMANTIC_COMPLETE", passed=False, reason="缺少有来源支持的失效原因。", kind="semantic"
            )], needs_revision=True)
        return ReviewResult(passed=True, checks=[ReviewCheck(
            check_id="SEMANTIC_COMPLETE", passed=True, kind="semantic"
        )])

    monkeypatch.setattr(graph, "semantic_review", review)
    model = RevisedAnswerModel()
    executor = graph_module.GraphExecutor(model, lambda _ctx: _registry(), model_mode="fake")
    ctx = RequestContext(owner_id="owner", request_id="request", run_id="run")
    request = ExecutorInput(run_id="run", thread_id="thread", message="解释报价情况。", ctx=ctx)
    sink = Sink()

    outcome = await executor.execute(request, sink, RunBudget("run"))

    assert outcome.status == "completed"
    assert semantic_answers == ["P003没有有效报价。", "P003没有有效报价；原因是报价已过期。"]
    published = "".join(payload["delta"] for kind, payload in sink.events if kind == "token")
    assert published == semantic_answers[-1]
    assert all(call[0].content.count("核验辅助事实：报价已过期。") == 1 for call in model.calls)
    assert all(next(message for message in call if message.role == "user").content == "解释报价情况。"
               for call in model.calls)


async def _registry():
    return EmptyRegistry()
