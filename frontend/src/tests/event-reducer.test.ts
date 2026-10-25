import { describe, expect, it } from "vitest";

import { applyEvent, emptyChatState, mergeArtifacts, mergeHistory } from "../lib/event-reducer";
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

  it("restores plan and review while preserving failed Run.status precedence", () => {
    let state = applyEvent(emptyChatState(), started);
    state = applyEvent(state, event({ type: "phase", seq: 2, payload: { phase: "result", task_type: "inventory", revision_count: 2 } }));
    state = applyEvent(state, event({ type: "plan", seq: 3, payload: { task_type: "inventory", items: [{ id: "read", title: "读取库存", status: "done", evidence_refs: [] }] } }));
    state = applyEvent(state, event({ type: "review", seq: 4, payload: { passed: false, revision_count: 2, details: [{ check_id: "NUMERIC_MATCH", passed: false, reason: "字段不匹配", evidence_refs: ["call-1/I001"] }], incomplete_items: ["NUMERIC_MATCH"] } }));
    state = applyEvent(state, event({ type: "run_finished", seq: 5, payload: { status: "failed", summary: "failed" } }));
    expect(state.phase).toBe("result");
    expect(state.plan[0].status).toBe("done");
    expect(state.review?.passed).toBe(false);
    expect(state.review?.checks?.[0].evidence_refs).toEqual(["call-1/I001"]);
    expect(state.runStatus).toBe("failed");
  });

  it("restores authorized artifact cards only from persisted artifact events", () => {
    const state = applyEvent(emptyChatState(), event({
      type: "artifact_ready", seq: 6,
      payload: { artifact_id: "art_abc", filename: "报价比较.png", kind: "png", mime: "image/png", source_refs: [{ entity: "quote", id: "Q01" }] },
    }));
    expect(state.artifacts).toHaveLength(1);
    expect(state.artifacts[0].artifact_id).toBe("art_abc");
    expect(state.artifacts[0].source_refs?.[0]?.id).toBe("Q01");
  });

  it("merges artifacts from every run in a thread without duplicating current-run events", () => {
    let state = applyEvent(emptyChatState("thr-1"), event({
      type: "artifact_ready", seq: 6,
      payload: { artifact_id: "art_new", filename: "new.csv", kind: "csv", mime: "text/csv" },
    }));
    state = mergeArtifacts(state, [
      { artifact_id: "art_old", filename: "old.csv", kind: "csv", run_id: "run-old" },
      { artifact_id: "art_new", filename: "new.csv", kind: "csv", run_id: "run-1" },
    ]);
    expect(state.artifacts.map((item) => item.artifact_id)).toEqual(["art_new", "art_old"]);
    expect(state.artifacts[0].run_id).toBe("run-1");
  });
});
