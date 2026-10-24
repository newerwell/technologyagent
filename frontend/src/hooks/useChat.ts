"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  cancelRun,
  ensureLocalSession,
  getConversation,
  getRun,
  getRunEvents,
} from "../lib/api";
import { applyEvent, emptyChatState, mergeHistory, type ChatState } from "../lib/event-reducer";
import type { EventEnvelope, ThreadView } from "../lib/events";
import { useHistory } from "./useHistory";
import { useSSE } from "./useSSE";

function messageOf(caught: unknown): string {
  if (caught instanceof ApiError) return caught.message;
  if (caught instanceof Error) return caught.message;
  return "聊天操作失败";
}

function syncUrl(threadId: string | null): void {
  if (typeof window === "undefined") return;
  const target = threadId ? "/chat?thread=" + encodeURIComponent(threadId) : "/chat";
  window.history.replaceState(null, "", target);
}

function initialThreadFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("thread");
}

export function useChat() {
  const { conversations, loading: historyLoading, error: historyError, refresh: refreshHistory } =
    useHistory();
  const { start: startSSE, abort: abortSSE } = useSSE();
  const [state, setState] = useState<ChatState>(() => emptyChatState());
  const [sending, setSending] = useState(false);
  const [busyError, setBusyError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const stateRef = useRef(state);
  const runIdRef = useRef<string | null>(null);
  const threadIdRef = useRef<string | null>(null);
  const lastSeqRef = useRef(0);
  const sendingRef = useRef(false);
  const initializedRef = useRef(false);

  const adopt = useCallback((next: ChatState) => {
    stateRef.current = next;
    runIdRef.current = next.runId;
    threadIdRef.current = next.threadId;
    lastSeqRef.current = next.lastSeq;
    setState(next);
  }, []);

  const applyIncoming = useCallback(
    (event: EventEnvelope) => {
      const next = applyEvent(stateRef.current, event);
      if (next === stateRef.current) return;
      adopt(next);
      if (event.type === "run_started") syncUrl(event.thread_id);
    },
    [adopt],
  );

  const loadThread = useCallback(
    async (threadId: string) => {
      abortSSE();
      sendingRef.current = false;
      setSending(false);
      setBusyError(null);
      try {
        await ensureLocalSession();
        const envelope = await getConversation(threadId);
        const conversation = envelope.data;
        if (!conversation) throw new Error("会话不存在");
        let next = emptyChatState(threadId);
        const latest = conversation.latest_run;
        if (latest) {
          next = { ...next, runId: latest.id, runStatus: latest.status, lastSeq: 0 };
          const events = await getRunEvents(latest.id, 0);
          for (const event of events.data ?? []) next = applyEvent(next, event);
        }
        next = mergeHistory(next, conversation.messages ?? []);
        if (latest) {
          next = { ...next, threadId, runId: latest.id, runStatus: latest.status };
        }
        adopt(next);
        syncUrl(threadId);
        void refreshHistory();
      } catch (caught) {
        setBusyError(messageOf(caught));
      }
    },
    [abortSSE, adopt, refreshHistory],
  );

  useEffect(() => {
    if (initializedRef.current || historyLoading) return;
    initializedRef.current = true;
    const threadId = initialThreadFromUrl();
    if (threadId) void loadThread(threadId);
  }, [historyLoading, loadThread]);

  const refreshAfterRun = useCallback(
    async (threadId: string, runId: string) => {
      try {
        const [runEnvelope, conversationEnvelope] = await Promise.all([
          getRun(runId),
          getConversation(threadId),
        ]);
        const current = stateRef.current;
        let next = mergeHistory(
          { ...current, runStatus: runEnvelope.data?.status ?? current.runStatus },
          conversationEnvelope.data?.messages ?? [],
        );
        next = {
          ...next,
          threadId,
          runId,
          runStatus: runEnvelope.data?.status ?? next.runStatus,
          lastSeq: Math.max(next.lastSeq, lastSeqRef.current),
        };
        adopt(next);
        await refreshHistory();
      } catch (caught) {
        setBusyError(messageOf(caught));
      }
    },
    [adopt, refreshHistory],
  );

  const recoverRun = useCallback(
    async (runId: string | null = runIdRef.current) => {
      if (!runId) return;
      try {
        const envelope = await getRun(runId);
        const run = envelope.data;
        if (!run) return;
        const events = await getRunEvents(runId, lastSeqRef.current);
        for (const event of events.data ?? []) applyIncoming(event);
        const current = stateRef.current;
        if (run.status !== current.runStatus) {
          adopt({ ...current, runStatus: run.status });
        }
        if (["completed", "failed", "cancelled", "waiting_input"].includes(run.status)) {
          const threadId = threadIdRef.current;
          if (threadId) {
            const conversation = await getConversation(threadId);
            adopt(mergeHistory(stateRef.current, conversation.data?.messages ?? []));
          }
          sendingRef.current = false;
          setSending(false);
          await refreshHistory();
        }
      } catch (caught) {
        setBusyError(messageOf(caught));
      }
    },
    [adopt, applyIncoming, refreshHistory],
  );

  useEffect(() => {
    if (!state.runId || state.runStatus !== "running" || sending) return;
    const timer = window.setInterval(() => {
      void recoverRun(state.runId);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [recoverRun, sending, state.runId, state.runStatus]);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || sendingRef.current || stateRef.current.runStatus === "running") return;
      const threadId = stateRef.current.threadId;
      try {
        await ensureLocalSession();
      } catch (caught) {
        setBusyError(messageOf(caught));
        return;
      }
      const requestId = crypto.randomUUID();
      const next = emptyChatState(threadId);
      adopt(next);
      setBusyError(null);
      setNotice(null);
      sendingRef.current = true;
      setSending(true);
      await startSSE(
        { thread_id: threadId || undefined, message, request_id: requestId },
        {
          onEvent: applyIncoming,
          onEnd: () => {
            sendingRef.current = false;
            setSending(false);
            const currentThread = threadIdRef.current;
            const currentRun = runIdRef.current;
            if (currentThread && currentRun) void refreshAfterRun(currentThread, currentRun);
            else void refreshHistory();
          },
          onAbort: () => {
            sendingRef.current = false;
            setSending(false);
          },
          onRecover: () => {
            sendingRef.current = false;
            setSending(false);
            void recoverRun();
          },
          onError: (caught) => {
            sendingRef.current = false;
            setSending(false);
            setBusyError(messageOf(caught));
          },
        },
      );
    },
    [adopt, applyIncoming, recoverRun, refreshAfterRun, refreshHistory, startSSE],
  );

  const cancel = useCallback(async () => {
    const runId = runIdRef.current;
    if (!runId) return;
    try {
      await cancelRun(runId);
      setNotice("已请求停止；后台会写回 cancelled 终态。");
    } catch (caught) {
      setBusyError(messageOf(caught));
    }
  }, []);

  const refresh = useCallback(async () => {
    abortSSE();
    sendingRef.current = false;
    setSending(false);
    setBusyError(null);
    await refreshHistory();
    const threadId = threadIdRef.current;
    if (threadId) await loadThread(threadId);
  }, [abortSSE, loadThread, refreshHistory]);

  const selectThread = useCallback(
    async (threadId: string) => {
      if (threadId === threadIdRef.current) return;
      await loadThread(threadId);
    },
    [loadThread],
  );

  const newChat = useCallback(() => {
    abortSSE();
    sendingRef.current = false;
    setSending(false);
    setBusyError(null);
    setNotice(null);
    adopt(emptyChatState(null));
    syncUrl(null);
  }, [abortSSE, adopt]);

  const busy = sending || state.runStatus === "running";
  const error = busyError ?? state.error ?? historyError;

  return {
    state,
    conversations: conversations as ThreadView[],
    historyLoading,
    sending,
    busy,
    error,
    notice,
    send,
    cancel,
    refresh,
    selectThread,
    newChat,
    dismissNotice: () => setNotice(null),
  };
}
