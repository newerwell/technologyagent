import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  ensureLocalSession: vi.fn(),
  getConversation: vi.fn(),
  getRunEvents: vi.fn(),
  getRun: vi.fn(),
  cancelRun: vi.fn(),
  listConversations: vi.fn(),
}));

const sse = vi.hoisted(() => ({
  start: vi.fn(),
  abort: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  ApiError: class ApiError extends Error {},
  ensureLocalSession: api.ensureLocalSession,
  getConversation: api.getConversation,
  getRunEvents: api.getRunEvents,
  getRun: api.getRun,
  cancelRun: api.cancelRun,
  listConversations: api.listConversations,
}));

vi.mock("./useHistory", () => ({
  useHistory: () => ({
    conversations: [],
    loading: false,
    error: null,
    refresh: vi.fn(async () => {}),
  }),
}));

vi.mock("./useSSE", () => ({
  useSSE: () => ({ start: sse.start, abort: sse.abort }),
}));

import { useChat } from "./useChat";

type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void; reject: (error: unknown) => void };

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function conversation(threadId: string) {
  return {
    data: {
      thread: {
        id: threadId,
        title: threadId,
        active_run_id: null,
        created_at: "2026-10-24T00:00:00Z",
        updated_at: "2026-10-24T00:00:00Z",
      },
      messages: [],
      latest_run: null,
    },
    meta: {},
  };
}

function runStarted(threadId: string, runId: string) {
  return {
    schema_version: 1,
    type: "run_started",
    event_id: "evt-" + runId,
    seq: 1,
    thread_id: threadId,
    run_id: runId,
    at: "2026-10-24T00:00:01Z",
    payload: { status: "running", thread_id: threadId, run_id: runId },
  };
}

function streamEnd(threadId: string, runId: string, seq: number) {
  return {
    schema_version: 1, type: "stream_end", event_id: "end-" + runId, seq,
    thread_id: threadId, run_id: runId, at: "2026-10-24T00:00:02Z",
    payload: { reason: "completed", last_seq: seq },
  };
}

beforeEach(() => {
  window.history.replaceState(null, "", "/chat");
  api.ensureLocalSession.mockResolvedValue({});
  api.getRunEvents.mockResolvedValue({ data: [] });
  api.getRun.mockResolvedValue({ data: { status: "completed" } });
  api.cancelRun.mockResolvedValue({ data: {} });
  api.getConversation.mockReset();
  sse.start.mockReset();
  sse.start.mockResolvedValue(undefined);
  sse.abort.mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("useChat view generation", () => {
  it("ignores a slow A load after B has been selected", async () => {
    const slowA = deferred<ReturnType<typeof conversation>>();
    const fastB = deferred<ReturnType<typeof conversation>>();
    api.getConversation.mockImplementation((threadId: string) =>
      threadId === "A" ? slowA.promise : fastB.promise,
    );
    const { result } = renderHook(() => useChat());

    await act(async () => {
      void result.current.selectThread("A");
      await Promise.resolve();
    });
    await act(async () => {
      void result.current.selectThread("B");
      await Promise.resolve();
    });
    fastB.resolve(conversation("B"));
    await waitFor(() => expect(result.current.state.threadId).toBe("B"));
    slowA.resolve(conversation("A"));
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.state.threadId).toBe("B");
    expect(window.location.search).toContain("thread=B");
  });

  it("does not restore a pending load after new chat", async () => {
    const slowA = deferred<ReturnType<typeof conversation>>();
    api.getConversation.mockReturnValue(slowA.promise);
    const { result } = renderHook(() => useChat());

    await act(async () => {
      void result.current.selectThread("A");
      await Promise.resolve();
    });
    act(() => result.current.newChat());
    slowA.resolve(conversation("A"));
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.state.threadId).toBeNull();
    expect(window.location.search).toBe("");
  });

  it("does not let an old load error overwrite the current view", async () => {
    const slowA = deferred<ReturnType<typeof conversation>>();
    const fastB = deferred<ReturnType<typeof conversation>>();
    api.getConversation.mockImplementation((threadId: string) =>
      threadId === "A" ? slowA.promise : fastB.promise,
    );
    const { result } = renderHook(() => useChat());
    await act(async () => {
      void result.current.selectThread("A");
      await Promise.resolve();
    });
    await act(async () => {
      void result.current.selectThread("B");
      await Promise.resolve();
    });
    fastB.resolve(conversation("B"));
    await waitFor(() => expect(result.current.state.threadId).toBe("B"));
    slowA.reject(new Error("old load failed"));
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.state.threadId).toBe("B");
    expect(result.current.error).toBeNull();
  });
});

describe("useChat send claim", () => {
  it("claims sending synchronously before the session await", async () => {
    const session = deferred<unknown>();
    api.ensureLocalSession.mockReturnValue(session.promise);
    const { result } = renderHook(() => useChat());

    await act(async () => {
      void result.current.send("first");
      void result.current.send("second");
      await Promise.resolve();
    });
    expect(result.current.sending).toBe(true);
    session.resolve({});
    await waitFor(() => expect(sse.start).toHaveBeenCalledTimes(1));
    expect(sse.start.mock.calls[0][0].message).toBe("first");
  });

  it("does not let an old stream abort release a newer send", async () => {
    const handlerList: Array<{ onEvent: (event: unknown) => void; onEnd: () => void; onAbort: () => void; onRecover: () => void; onError: (error: unknown) => void }> = [];
    sse.start.mockImplementation(async (_body: unknown, handlers: (typeof handlerList)[number]) => {
      handlerList.push(handlers);
      return new Promise<void>(() => {});
    });
    api.ensureLocalSession.mockResolvedValue({});
    const fastB = deferred<ReturnType<typeof conversation>>();
    api.getConversation.mockReturnValue(fastB.promise);
    const { result } = renderHook(() => useChat());

    await act(async () => {
      void result.current.send("old");
      await Promise.resolve();
    });
    await act(async () => {
      void result.current.selectThread("B");
      await Promise.resolve();
    });
    fastB.resolve(conversation("B"));
    await waitFor(() => expect(result.current.state.threadId).toBe("B"));
    await act(async () => {
      void result.current.send("new");
      await Promise.resolve();
    });
    expect(sse.start).toHaveBeenCalledTimes(2);
    expect(result.current.sending).toBe(true);
    act(() => handlerList[0].onAbort());
    expect(result.current.sending).toBe(true);
    expect(result.current.state.threadId).toBe("B");
  });

  it("does not let old stream end release a newer view", async () => {
    let handlers: {
      onEvent: (event: unknown) => void;
      onEnd: () => void;
      onAbort: () => void;
      onRecover: () => void;
      onError: (error: unknown) => void;
    } | null = null;
    sse.start.mockImplementation(async (_body: unknown, nextHandlers: typeof handlers) => {
      handlers = nextHandlers;
      return new Promise<void>(() => {});
    });
    api.ensureLocalSession.mockResolvedValue({});
    const slowB = deferred<ReturnType<typeof conversation>>();
    api.getConversation.mockReturnValue(slowB.promise);
    const { result } = renderHook(() => useChat());

    await act(async () => {
      void result.current.send("old stream");
      await Promise.resolve();
    });
    expect(handlers).not.toBeNull();
    act(() => {
      handlers?.onEvent(runStarted("old-thread", "old-run"));
    });
    await waitFor(() => expect(result.current.state.threadId).toBe("old-thread"));

    await act(async () => {
      void result.current.selectThread("B");
      await Promise.resolve();
    });
    slowB.resolve(conversation("B"));
    await waitFor(() => expect(result.current.state.threadId).toBe("B"));
    act(() => handlers?.onEnd());
    expect(result.current.state.threadId).toBe("B");
  });

  it("does not let old same-view refresh overwrite a newly started run", async () => {
    const handlers: Array<{
      onEvent: (event: never) => void; onEnd: () => void; onAbort: () => void;
      onRecover: () => void; onError: (error: unknown) => void;
    }> = [];
    sse.start.mockImplementation(async (_body: unknown, next: (typeof handlers)[number]) => {
      handlers.push(next);
      return new Promise<void>(() => {});
    });
    const oldRun = deferred<unknown>();
    const oldConversation = deferred<ReturnType<typeof conversation>>();
    api.getRun.mockImplementation((runId: string) => runId === "old-run" ? oldRun.promise : Promise.resolve({ data: { status: "running" } }));
    api.getConversation.mockImplementation((_threadId: string) => oldConversation.promise);
    const { result } = renderHook(() => useChat());
    await act(async () => { void result.current.send("old"); await Promise.resolve(); });
    act(() => handlers[0].onEvent(runStarted("thread", "old-run") as never));
    act(() => handlers[0].onEvent(streamEnd("thread", "old-run", 2) as never));
    act(() => handlers[0].onEnd());
    await act(async () => { void result.current.send("new"); await Promise.resolve(); });
    act(() => handlers[1].onEvent(runStarted("thread", "new-run") as never));
    expect(result.current.state.runId).toBe("new-run");
    oldRun.resolve({ data: { status: "completed" } });
    oldConversation.resolve(conversation("thread"));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    act(() => handlers[1].onEvent({ ...runStarted("thread", "new-run"), type: "token", event_id: "token-new", seq: 2, payload: { message_id: "m-new", delta: "new answer" } } as never));
    expect(result.current.state.runId).toBe("new-run");
    expect(result.current.state.runStatus).toBe("running");
    expect(result.current.state.messages.map((message) => message.content)).toEqual(["new answer"]);
  });
});
