import asyncio

import pytest
import httpx

from backend.app.contracts.agent import ModelDelta
from backend.app.contracts.common import RequestContext
from backend.app.agent.budget import RunBudget, RunCancelled, RunLimitExceeded
from backend.app.integrations.model import ModelProviderError
from backend.app.services import model_observation
from backend.app.services.model_observation import observed_model_stream


class _Model:
    def __init__(self, *, fail=False):
        self.fail = fail

    async def stream(self, messages, tools, ctx):
        if self.fail:
            raise RuntimeError("provider unavailable")
        yield ModelDelta(kind="usage", usage={"total_tokens": 10, "api_key": "must-not-leak"})
        yield ModelDelta(kind="token", content="ok")


@pytest.mark.asyncio
async def test_model_observer_emits_purpose_and_sanitized_usage():
    events = []

    async def emit(kind, payload):
        events.append((kind, payload))

    deltas = [delta async for delta in observed_model_stream(
        _Model(), [], [], RequestContext("owner", "request", run_id="run"), emit,
        purpose="semantic_review",
    )]

    assert [delta.kind for delta in deltas] == ["usage", "token"]
    assert [kind for kind, _ in events] == ["model_started", "model_finished"]
    assert events[0][1]["purpose"] == "semantic_review"
    assert events[0][1]["call_id"] == events[1][1]["call_id"]
    assert events[1][1]["usage_status"] == "reported"
    assert events[1][1]["usage"] == {"total_tokens": 10}


@pytest.mark.asyncio
async def test_model_observer_records_error_finish_before_reraising():
    events = []

    async def emit(kind, payload):
        events.append((kind, payload))

    with pytest.raises(RuntimeError, match="provider unavailable"):
        async for _ in observed_model_stream(
            _Model(fail=True), [], [], RequestContext("owner", "request", run_id="run"), emit,
            purpose="order_intent_extract",
        ):
            pass

    assert [kind for kind, _ in events] == ["model_started", "model_finished"]
    assert events[1][1]["status"] == "error"
    assert events[1][1]["usage_status"] == "missing"


class _ScriptedStream:
    def __init__(self, actions, *, budget=None):
        self.actions = list(actions)
        self.calls = 0
        self.budget = budget

    async def stream(self, messages, tools, ctx):
        self.calls += 1
        actions = self.actions[min(self.calls - 1, len(self.actions) - 1)]
        for action in actions:
            if isinstance(action, BaseException):
                raise action
            if self.budget is not None and action == "cancel_then_transport":
                self.budget.cancel()
                raise httpx.ReadError("connection interrupted before first delta")
            yield action


def _collection_function():
    function = getattr(model_observation, "collect_model_response", None)
    assert callable(function), "model_observation.collect_model_response is required"
    return function


@pytest.mark.asyncio
async def test_collect_model_response_retries_only_pre_delta_transport_and_returns_success_attempt():
    events = []
    budget_charges = []

    async def emit(kind, payload):
        events.append((kind, payload))

    async def charge():
        budget_charges.append(1)
        return True

    budget = RunBudget("run", model_counter=charge)
    model = _ScriptedStream(
        [[httpx.RemoteProtocolError("connection dropped before response")], [
            ModelDelta(kind="token", content="complete"),
            ModelDelta(kind="usage", usage={"total_tokens": 9}),
        ]]
    )
    response = await _collection_function()(
        model, [], [], RequestContext("owner", "request", run_id="run"), budget, emit,
        purpose="agent_step",
    )

    assert [item.content for item in response.deltas if item.kind == "token"] == ["complete"]
    assert response.successful_call_id.startswith("model_")
    assert response.usage == {"total_tokens": 9}
    assert model.calls == len(budget_charges) == 2
    started = [payload for kind, payload in events if kind == "model_started"]
    finished = [payload for kind, payload in events if kind == "model_finished"]
    assert len(started) == len(finished) == 2
    assert started[0]["call_id"] == finished[0]["call_id"]
    assert started[1]["call_id"] == finished[1]["call_id"] == response.successful_call_id
    assert len({item["call_id"] for item in started}) == 2
    assert finished[0]["status"] == "error"
    assert finished[1]["status"] == "success"


@pytest.mark.asyncio
async def test_collect_model_response_stops_after_two_pre_delta_transport_failures():
    events = []
    charges = []

    async def emit(kind, payload):
        events.append((kind, payload))

    async def charge():
        charges.append(1)
        return True

    model = _ScriptedStream([
        [httpx.ReadError("first connection failed")],
        [httpx.RemoteProtocolError("second connection failed")],
    ])
    with pytest.raises(httpx.RemoteProtocolError):
        await _collection_function()(
            model, [], [], RequestContext("owner", "request"),
            RunBudget("run", model_counter=charge), emit, purpose="agent_step",
        )

    assert model.calls == len(charges) == 2
    assert len([kind for kind, _ in events if kind == "model_started"]) == 2
    assert len([kind for kind, _ in events if kind == "model_finished"]) == 2
    assert all(payload["status"] == "error" for kind, payload in events if kind == "model_finished")


@pytest.mark.asyncio
@pytest.mark.parametrize("delta", [
    ModelDelta(kind="token", content="partial"),
    ModelDelta(kind="tool_call"),
    ModelDelta(kind="usage", usage={"total_tokens": 1}),
])
async def test_collect_model_response_never_retries_after_any_delta(delta):
    events = []
    charges = []

    async def emit(kind, payload):
        events.append((kind, payload))

    async def charge():
        charges.append(1)
        return True

    model = _ScriptedStream([[delta, httpx.ReadError("dropped after delta")]])
    with pytest.raises(httpx.ReadError):
        await _collection_function()(
            model, [], [], RequestContext("owner", "request"), RunBudget("run", model_counter=charge), emit,
            purpose="semantic_review",
        )

    assert model.calls == len(charges) == 1
    assert [kind for kind, _ in events] == ["model_started", "model_finished"]
    assert events[-1][1]["status"] == "error"


@pytest.mark.asyncio
async def test_collect_model_response_does_not_retry_protocol_error_even_when_retryable_flag_is_set():
    events = []
    error = ModelProviderError(
        "provider rejected request", code="MODEL_PROVIDER_ERROR", retryable=True
    )
    model = _ScriptedStream([[error]])

    async def emit(kind, payload):
        events.append((kind, payload))

    with pytest.raises(ModelProviderError):
        await _collection_function()(
            model, [], [], RequestContext("owner", "request"), RunBudget("run"), emit,
            purpose="agent_step",
        )

    assert model.calls == 1
    assert [kind for kind, _ in events] == ["model_started", "model_finished"]


@pytest.mark.asyncio
async def test_collect_model_response_does_not_start_retry_after_budget_or_cancel():
    async def run_case(actions, *, allowed):
        events = []
        charges = []

        async def emit(kind, payload):
            events.append((kind, payload))

        async def charge():
            charges.append(1)
            return len(charges) <= allowed

        budget = RunBudget("run", model_counter=charge)
        model = _ScriptedStream(actions, budget=budget)
        return events, charges, model, budget

    events, charges, model, budget = await run_case(
        [[httpx.ReadError("first attempt failed")], [ModelDelta(kind="token", content="ok")]], allowed=1
    )
    with pytest.raises(RunLimitExceeded):
        await _collection_function()(
            model, [], [], RequestContext("owner", "request"), budget,
            lambda kind, payload: _record(events, kind, payload), purpose="agent_step",
        )
    assert model.calls == 1
    assert len([kind for kind, _ in events if kind == "model_started"]) == 1

    events, charges, model, budget = await run_case([[
        "cancel_then_transport",
    ]], allowed=2)
    with pytest.raises(RunCancelled):
        await _collection_function()(
            model, [], [], RequestContext("owner", "request"), budget,
            lambda kind, payload: _record(events, kind, payload), purpose="agent_step",
        )
    assert model.calls == 1
    assert len([kind for kind, _ in events if kind == "model_started"]) == 1


@pytest.mark.asyncio
async def test_collect_model_response_cancels_idle_provider_task_when_run_is_cancelled():
    events = []
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    class IdleModel:
        async def stream(self, messages, tools, ctx):
            entered.set()
            try:
                await asyncio.Event().wait()
                yield ModelDelta(kind="token", content="unreachable")
            finally:
                cleaned.set()

    async def emit(kind, payload):
        events.append((kind, payload))

    budget = RunBudget("run")
    task = asyncio.create_task(_collection_function()(
        IdleModel(), [], [], RequestContext("owner", "request"), budget, emit,
        purpose="semantic_review",
    ))
    await asyncio.wait_for(entered.wait(), timeout=1)
    budget.cancel()
    with pytest.raises(RunCancelled):
        await asyncio.wait_for(task, timeout=1)

    assert cleaned.is_set()
    assert [kind for kind, _ in events] == ["model_started", "model_finished"]
    assert events[-1][1]["status"] == "error"
    assert events[-1][1]["error_code"] == "RUNCANCELLED"


@pytest.mark.asyncio
async def test_collect_model_response_enforces_one_logical_deadline_and_cleans_up():
    events = []
    entered = 0
    cleaned = 0

    class IdleModel:
        async def stream(self, messages, tools, ctx):
            nonlocal entered, cleaned
            entered += 1
            try:
                await asyncio.Event().wait()
                yield ModelDelta(kind="token", content="unreachable")
            finally:
                cleaned += 1

    async def emit(kind, payload):
        events.append((kind, payload))

    with pytest.raises(ModelProviderError) as raised:
        await asyncio.wait_for(_collection_function()(
            IdleModel(), [], [], RequestContext("owner", "request"), RunBudget("run"), emit,
            purpose="semantic_review", timeout_seconds=0.02,
        ), timeout=1)

    assert raised.value.code == "MODEL_TIMEOUT"
    assert entered == cleaned == 1
    assert [kind for kind, _ in events] == ["model_started", "model_finished"]
    assert events[-1][1]["status"] == "error"


@pytest.mark.asyncio
async def test_collect_model_response_rejects_success_completed_after_shared_deadline(monkeypatch):
    events = []
    clock = [0.0]
    monkeypatch.setattr(model_observation, "perf_counter", lambda: clock[0])

    class LateSuccess:
        def __init__(self):
            self.calls = 0

        async def stream(self, messages, tools, ctx):
            self.calls += 1
            if self.calls == 1:
                clock[0] = 0.8
                raise httpx.ReadError("transient interruption")
            await asyncio.sleep(0.01)
            clock[0] = 1.1
            yield ModelDelta(kind="token", content="too late")

    async def emit(kind, payload):
        events.append((kind, payload))

    model = LateSuccess()
    with pytest.raises(ModelProviderError) as raised:
        await _collection_function()(
            model, [], [], RequestContext("owner", "request"), RunBudget("run"), emit,
            purpose="agent_step", timeout_seconds=1,
        )

    assert raised.value.code == "MODEL_TIMEOUT"
    assert model.calls == 2
    assert [item[1]["status"] for item in events if item[0] == "model_finished"] == ["error", "error"]


async def _record(events, kind, payload):
    events.append((kind, payload))
