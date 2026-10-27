from __future__ import annotations

import asyncio

from backend.app.agent.graph_versions import _preference_command
from backend.app.agent.budget import RunBudget
from backend.app.contracts.agent import ExecutorInput
from backend.app.contracts.common import RequestContext


def test_preference_save_emits_pass_review_after_persisted_readback():
    class Preferences:
        def __init__(self):
            self.values = {}

        async def remember(self, _owner, request):
            self.values[request.key] = request.value

        async def list(self, _owner):
            return dict(self.values)

    class Executor:
        _preferences = Preferences()

    class Sink:
        def __init__(self):
            self.events = []

        async def emit(self, kind, payload):
            self.events.append((kind, payload))

    request = ExecutorInput(run_id="pref-run", thread_id="thread", message="记住默认仓库W01",
                            ctx=RequestContext(owner_id="owner-a", request_id="request", run_id="pref-run"),
                            graph_version="v2")
    sink = Sink()
    outcome = asyncio.run(_preference_command(Executor(), request, sink, "remember", {"default_warehouse": "W01"}))

    assert outcome.status == "completed"
    assert Executor._preferences.values == {"default_warehouse": "W01"}
    assert [(kind, payload["passed"], payload["checks"]) for kind, payload in sink.events] == [
        ("review", True, ["PREFERENCE_PERSISTED"])
    ]
