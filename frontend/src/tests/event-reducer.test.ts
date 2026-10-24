import { describe, expect, it } from "vitest";

import { applyEvent, emptyChatState, mergeHistory } from "../lib/event-reducer";
import type { EventEnvelope } from "../lib/events";

function event(overrides: Partial<EventEnvelope> & { type: string; seq: number; payload: object }): EventEnvelope {
  return {
    schema_version: 1,
    event_id: "evt-" + overrides.seq,
    thread_id: "thr-1",
    run_id: "run-1",
    at: "2026-10-24T01:00:0" + overrides.seq + "Z",
    ...overrides,
  } as EventEnvelope;
}

const started = event({
  type: "run_started",
  seq: 1,
  payload: { status: "running", thread_id: "thr-1", run_id: "run-1" },
});
const token = event({
  type: "token",
  seq: 2,
  payload: { message_id: "msg-1", delta: "你好", actor: "main" },
});
const end = event({
  type: "stream_end",
  seq: 3,
  payload: { reason: "completed", last_seq: 3 },
});

describe("event reducer", () => {
  it("deduplicates by run+seq and merges final history by message id", () => {
    let state = emptyChatState();
    state = applyEvent(state, started);
    state = applyEvent(state, token);
    const once = state.messages[0].content;
    state = applyEvent(state, token);
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0].content).toBe(once);

    state = mergeHistory(state, [
      {
        id: "msg-1",
        role: "assistant",
        content: "你好，完整历史",
        created_at: "2026-10-24T01:00:02Z",
        run_id: "run-1",
      },
    ]);
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0].content).toBe("你好，完整历史");
    state = applyEvent(state, end);
    expect(state.streamEnded).toBe(true);
  });

  it("pairs tool cards and ignores future compatible events", () => {
    let state = emptyChatState();
    state = applyEvent(state, started);
    state = applyEvent(
      state,
      event({
        type: "tool_started",
        seq: 2,
        payload: { call_id: "call-1", name: "fake", actor: "main", args_summary: {}, simulation: true },
      }),
    );
    expect(state.tools[0].status).toBe("running");
    state = applyEvent(
      state,
      event({
        type: "tool_finished",
        seq: 3,
        payload: { call_id: "call-1", status: "success", result_summary: "ok", source: "fake", simulation: true },
      }),
    );
    expect(state.tools[0].status).toBe("success");
    state = applyEvent(
      state,
      event({ type: "phase", seq: 4, payload: { phase: "executing", iteration: 0 } }),
    );
    expect(state.lastSeq).toBe(4);
  });

  it("keeps a structured interrupt through waiting_input and clears it after completion", () => {
    let state = applyEvent(emptyChatState(), started);
    state = applyEvent(state, event({
      type: "interrupt", seq: 2,
      payload: { interrupt_id: "int-1", kind: "approval", draft_id: "drf-1", version: 1, fields: [] },
    }));
    expect(state.pendingInterrupt?.draft_id).toBe("drf-1");
    state = applyEvent(state, event({
      type: "stream_end", seq: 3, payload: { reason: "waiting_input", last_seq: 3 },
    }));
    expect(state.pendingInterrupt?.interrupt_id).toBe("int-1");
    state = applyEvent(state, event({
      type: "run_finished", seq: 4, payload: { status: "completed", summary: "done" },
    }));
    expect(state.pendingInterrupt).toBeNull();
  });
});
