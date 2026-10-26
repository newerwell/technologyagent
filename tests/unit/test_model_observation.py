import pytest

from backend.app.contracts.agent import ModelDelta
from backend.app.contracts.common import RequestContext
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
