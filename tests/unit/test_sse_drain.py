"""P02-R06 SSE 终态排空：get 看到终态但 events 首批未包含 stream_end 时不漏。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.api.chat import stream_run_events
from backend.app.contracts.common import RequestContext
from backend.app.contracts.events import EventEnvelope, RunView


def event(seq: int, type_name: str, payload: dict) -> EventEnvelope:
    return EventEnvelope(
        type=type_name,
        event_id="evt-" + str(seq),
        seq=seq,
        thread_id="thr-1",
        run_id="run-1",
        at=datetime(2026, 10, 24, 1, 0, seq, tzinfo=timezone.utc),
        payload=payload,
    )


def run_view(status: str, last_seq: int) -> RunView:
    now = datetime(2026, 10, 24, 1, 0, 0, tzinfo=timezone.utc)
    return RunView(
        id="run-1",
        thread_id="thr-1",
        status=status,
        last_seq=last_seq,
        created_at=now,
        updated_at=now,
        finished_at=now,
    )


class FakeRuns:
    def __init__(self, batches):
        self._batches = batches
        self.calls = 0

    async def events(self, run_id, after_seq, ctx):
        batch = self._batches[min(self.calls, len(self._batches) - 1)]
        self.calls += 1
        return [item for item in batch if item.seq > after_seq]

    async def get(self, run_id, ctx):
        return run_view("completed", 2)


@pytest.mark.asyncio
async def test_stream_drains_terminal_events_after_empty_first_poll():
    finished = event(1, "run_finished", {"status": "completed", "summary": "done"})
    end = event(2, "stream_end", {"reason": "completed", "last_seq": 2})
    runs = FakeRuns([[], [finished, end]])
    chunks = [chunk async for chunk in stream_run_events(runs, "run-1", RequestContext("owner", "req"))]
    assert len(chunks) == 2
    assert '"type":"run_finished"' in chunks[0]
    assert '"type":"stream_end"' in chunks[1]
    assert runs.calls >= 2


@pytest.mark.asyncio
async def test_stream_yields_missing_stream_end_after_terminal_run_finished():
    finished = event(1, "run_finished", {"status": "completed", "summary": "done"})
    end = event(2, "stream_end", {"reason": "completed", "last_seq": 2})
    runs = FakeRuns([[finished], [end]])
    chunks = [chunk async for chunk in stream_run_events(runs, "run-1", RequestContext("owner", "req"))]
    assert len(chunks) == 2
    assert chunks[-1].startswith("id: evt-2")
