import type { EventEnvelope } from "./events";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  runId: string;
  streaming: boolean;
};

export type ChatTool = {
  callId: string;
  name: string;
  actor: string;
  status: "running" | "success" | "error";
  argsSummary: Record<string, unknown>;
  resultSummary: string;
  source: string;
  error: string | null;
  simulation: boolean;
};

export type ChatState = {
  threadId: string | null;
  runId: string | null;
  runStatus: string | null;
  lastSeq: number;
  messages: ChatMessage[];
  tools: ChatTool[];
  streamEnded: boolean;
  streamReason: string | null;
  error: string | null;
  modelMode: "fake" | "live";
  fake: boolean;
};

export function emptyChatState(threadId: string | null = null): ChatState {
  return {
    threadId,
    runId: null,
    runStatus: null,
    lastSeq: 0,
    messages: [],
    tools: [],
    streamEnded: false,
    streamReason: null,
    error: null,
    modelMode: "fake",
    fake: true,
  };
}

function upsertAssistant(
  messages: ChatMessage[],
  messageId: string,
  delta: string,
  createdAt: string,
  runId: string,
): ChatMessage[] {
  const index = messages.findIndex((message) => message.id === messageId);
  if (index < 0) {
    return [
      ...messages,
      {
        id: messageId,
        role: "assistant",
        content: delta,
        createdAt,
        runId,
        streaming: true,
      },
    ];
  }
  const next = [...messages];
  next[index] = { ...next[index], content: next[index].content + delta, streaming: true };
  return next;
}

export function applyEvent(state: ChatState, event: EventEnvelope): ChatState {
  if (state.runId !== null && event.run_id !== state.runId) return state;
  if (event.seq <= state.lastSeq) return state;
  const base: ChatState = {
    ...state,
    threadId: event.thread_id,
    runId: event.run_id,
    lastSeq: event.seq,
  };
  switch (event.type) {
    case "run_started": {
      const modelMode = event.payload.model_mode === "live" ? "live" : "fake";
      return {
        ...base,
        runStatus: event.payload.status,
        streamEnded: false,
        error: null,
        modelMode,
        fake: modelMode === "fake",
      };
    }
    case "token":
      return {
        ...base,
        messages: upsertAssistant(
          base.messages,
          event.payload.message_id,
          event.payload.delta,
          event.at,
          event.run_id,
        ),
      };
    case "tool_started": {
      const tool: ChatTool = {
        callId: event.payload.call_id,
        name: event.payload.name,
        actor: event.payload.actor ?? "main",
        status: "running",
        argsSummary: event.payload.args_summary ?? {},
        resultSummary: "",
        source: "",
        error: null,
        simulation: event.payload.simulation ?? false,
      };
      return { ...base, tools: [...base.tools.filter((item) => item.callId !== tool.callId), tool] };
    }
    case "tool_finished":
      return {
        ...base,
        tools: base.tools.map((tool) =>
          tool.callId === event.payload.call_id
            ? {
                ...tool,
                status: event.payload.status,
                resultSummary: event.payload.result_summary ?? "",
                source: event.payload.source ?? "",
                error: event.payload.error ?? null,
                simulation: event.payload.simulation ?? tool.simulation,
              }
            : tool,
        ),
      };
    case "error":
      return { ...base, error: event.payload.message };
    case "run_finished":
      return { ...base, runStatus: event.payload.status };
    case "stream_end":
      return {
        ...base,
        streamEnded: true,
        streamReason: event.payload.reason,
        runStatus: event.payload.reason === "waiting_input" ? "waiting_input" : event.payload.reason,
      };
    case "interrupt":
    case "phase":
    case "plan":
    case "review":
    case "artifact_ready":
      return base;
    default:
      return base;
  }
}

export function mergeHistory(
  state: ChatState,
  history: Array<{
    id: string;
    role: "user" | "assistant";
    content: string;
    created_at: string;
    run_id: string;
  }>,
): ChatState {
  const byId = new Map(state.messages.map((message) => [message.id, message]));
  for (const item of history) {
    byId.set(item.id, {
      id: item.id,
      role: item.role,
      content: item.content,
      createdAt: item.created_at,
      runId: item.run_id,
      streaming: false,
    });
  }
  const messages = [...byId.values()].sort((left, right) => {
    const a = left.createdAt.localeCompare(right.createdAt);
    return a !== 0 ? a : left.id.localeCompare(right.id);
  });
  return { ...state, messages };
}
