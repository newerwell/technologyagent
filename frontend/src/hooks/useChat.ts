"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  cancelRun,
  ensureLocalSession,
  getConversation,
  resumeOrderRun,
  getRun,
  getRunEvents,
  getThreadArtifacts,
} from "../lib/api";
import { applyEvent, emptyChatState, mergeArtifacts, mergeHistory, type ChatState } from "../lib/event-reducer";
import type { EventEnvelope, ThreadView } from "../lib/events";
import { useHistory } from "./useHistory";
import { useSSE } from "./useSSE";

type SendToken = { generation: number; id: number };

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
  const viewGenerationRef = useRef(0);
  const sendSequenceRef = useRef(0);
  const runOperationRef = useRef(0);
  const sendTokenRef = useRef<SendToken | null>(null);
  const initializedRef = useRef(false);

  const adopt = useCallback((next: ChatState) => {
    stateRef.current = next;
    runIdRef.current = next.runId;
    threadIdRef.current = next.threadId;
    lastSeqRef.current = next.lastSeq;
    setState(next);
  }, []);

  const isCurrentView = useCallback(
    (generation: number) => generation === viewGenerationRef.current,
    [],
  );

  const invalidateView = useCallback(() => {
    viewGenerationRef.current += 1;
    sendTokenRef.current = null;
    sendingRef.current = false;
    setSending(false);
    abortSSE();
    return viewGenerationRef.current;
  }, [abortSSE]);

  const releaseSend = useCallback((token: SendToken) => {
    if (sendTokenRef.current !== token) return false;
    sendTokenRef.current = null;
    sendingRef.current = false;
    setSending(false);
    return true;
  }, []);

  const applyIncoming = useCallback(
    (event: EventEnvelope, generation: number) => {
      if (!isCurrentView(generation)) return;
      const next = applyEvent(stateRef.current, event);
      if (next === stateRef.current) return;
      adopt(next);
      if (event.type === "run_started") syncUrl(event.thread_id);
    },
    [adopt, isCurrentView],
  );

  const loadThread = useCallback(
    async (threadId: string) => {
      const generation = invalidateView();
      setBusyError(null);
      try {
        await ensureLocalSession();
        if (!isCurrentView(generation)) return;
        const envelope = await getConversation(threadId);
        if (!isCurrentView(generation)) return;
        const conversation = envelope.data;
        if (!conversation) throw new Error("会话不存在");
        let next = emptyChatState(threadId);
        const latest = conversation.latest_run;
        if (latest) {
          next = { ...next, runId: latest.id, runStatus: latest.status,
            runSummary: latest.summary ?? "", committedFacts: latest.committed_facts ?? false,
            pendingInterrupt: latest.pending_interrupt ?? null, lastSeq: 0,
            phase: latest.phase ?? null, taskType: latest.task_type ?? "general", plan: latest.plan ?? [], review: latest.review ?? null, revisionCount: latest.revision_count ?? 0 };
          const events = await getRunEvents(latest.id, 0);
          if (!isCurrentView(generation)) return;
          for (const event of events.data ?? []) next = applyEvent(next, event);
        }
        const artifacts = await getThreadArtifacts(threadId);
        if (!isCurrentView(generation)) return;
        next = mergeArtifacts(next, artifacts.data ?? []);
        next = mergeHistory(next, conversation.messages ?? []);
        if (latest) {
          next = { ...next, threadId, runId: latest.id, runStatus: latest.status };
        }
        adopt(next);
        syncUrl(threadId);
        void refreshHistory();
      } catch (caught) {
        if (isCurrentView(generation)) setBusyError(messageOf(caught));
      }
    },
    [adopt, invalidateView, isCurrentView, refreshHistory],
  );

  useEffect(() => {
    if (initializedRef.current || historyLoading) return;
    initializedRef.current = true;
    const threadId = initialThreadFromUrl();
    if (threadId) void loadThread(threadId);
  }, [historyLoading, loadThread]);

  useEffect(() => {
    return () => {
      viewGenerationRef.current += 1;
      sendTokenRef.current = null;
      abortSSE();
    };
  }, [abortSSE]);

  const refreshAfterRun = useCallback(
    async (threadId: string, runId: string, generation: number, operation: number) => {
      try {
        const [runEnvelope, conversationEnvelope, artifactEnvelope] = await Promise.all([
          getRun(runId),
          getConversation(threadId),
          getThreadArtifacts(threadId),
        ]);
        if (!isCurrentView(generation) || runOperationRef.current !== operation || runIdRef.current !== runId) return;
        const current = stateRef.current;
        let next = mergeHistory(
          { ...current, runStatus: runEnvelope.data?.status ?? current.runStatus },
          conversationEnvelope.data?.messages ?? [],
        );
        next = mergeArtifacts(next, artifactEnvelope.data ?? []);
        next = {
          ...next,
          threadId,
          runId,
          runStatus: runEnvelope.data?.status ?? next.runStatus,
          runSummary: runEnvelope.data?.summary ?? next.runSummary,
          committedFacts: runEnvelope.data?.committed_facts ?? next.committedFacts,
          pendingInterrupt: runEnvelope.data?.pending_interrupt ?? null,
          phase: runEnvelope.data?.phase ?? next.phase,
          taskType: runEnvelope.data?.task_type ?? next.taskType,
          plan: runEnvelope.data?.plan ?? next.plan,
          review: runEnvelope.data?.review ?? next.review,
          revisionCount: runEnvelope.data?.revision_count ?? next.revisionCount,
          lastSeq: Math.max(next.lastSeq, lastSeqRef.current),
        };
        adopt(next);
        await refreshHistory();
      } catch (caught) {
        if (isCurrentView(generation) && runOperationRef.current === operation && runIdRef.current === runId) setBusyError(messageOf(caught));
      }
    },
    [adopt, isCurrentView, refreshHistory],
  );

  const recoverRun = useCallback(
    async (runId: string | null = runIdRef.current, generation = viewGenerationRef.current) => {
      if (!runId || !isCurrentView(generation) || sendingRef.current) return;
      const operation = runOperationRef.current;
      try {
        const envelope = await getRun(runId);
        if (!isCurrentView(generation) || runOperationRef.current !== operation || runIdRef.current !== runId) return;
        const run = envelope.data;
        if (!run) return;
        const events = await getRunEvents(runId, lastSeqRef.current);
        if (!isCurrentView(generation) || runOperationRef.current !== operation || runIdRef.current !== runId) return;
        for (const event of events.data ?? []) applyIncoming(event, generation);
        const current = stateRef.current;
        if (run.status !== current.runStatus) {
          adopt({ ...current, runStatus: run.status, pendingInterrupt: run.pending_interrupt ?? null,
            runSummary: run.summary ?? current.runSummary,
            committedFacts: run.committed_facts ?? current.committedFacts,
            phase: run.phase ?? current.phase, taskType: run.task_type ?? current.taskType,
            plan: run.plan ?? current.plan, review: run.review ?? current.review,
            revisionCount: run.revision_count ?? current.revisionCount });
        }
        if (["completed", "failed", "cancelled", "waiting_input"].includes(run.status)) {
          const threadId = threadIdRef.current;
          if (threadId) {
            const conversation = await getConversation(threadId);
            if (!isCurrentView(generation) || runOperationRef.current !== operation || runIdRef.current !== runId) return;
            adopt(mergeHistory(stateRef.current, conversation.data?.messages ?? []));
          }
          await refreshHistory();
        }
      } catch (caught) {
        if (isCurrentView(generation) && runOperationRef.current === operation && runIdRef.current === runId) setBusyError(messageOf(caught));
      }
    },
    [adopt, applyIncoming, isCurrentView, refreshHistory],
  );

  useEffect(() => {
    if (!state.runId || state.runStatus !== "running" || sending) return;
    const timer = window.setInterval(() => {
      void recoverRun(state.runId, viewGenerationRef.current);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [recoverRun, sending, state.runId, state.runStatus]);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || sendingRef.current || stateRef.current.runStatus === "running") return;
      const generation = viewGenerationRef.current;
      const operation = ++runOperationRef.current;
      const token: SendToken = {
        generation,
        id: ++sendSequenceRef.current,
      };
      const threadId = stateRef.current.threadId;
      sendTokenRef.current = token;
      sendingRef.current = true;
      setSending(true);
      setBusyError(null);
      setNotice(null);
      const existingArtifacts = stateRef.current.threadId === threadId ? stateRef.current.artifacts : [];
      adopt({ ...emptyChatState(threadId), artifacts: existingArtifacts });
      try {
        await ensureLocalSession();
      } catch (caught) {
        if (releaseSend(token) && isCurrentView(generation)) {
          setBusyError(messageOf(caught));
        }
        return;
      }
      if (sendTokenRef.current !== token || !isCurrentView(generation)) return;
      if (stateRef.current.runStatus === "running") {
        releaseSend(token);
        return;
      }
      const requestId = crypto.randomUUID();
      await startSSE(
        { thread_id: threadId || undefined, message, request_id: requestId },
        {
          onEvent: (event) => applyIncoming(event, generation),
          onEnd: () => {
            if (sendTokenRef.current !== token) return;
            releaseSend(token);
            if (!isCurrentView(generation)) return;
            const currentThread = threadIdRef.current;
            const currentRun = runIdRef.current;
            if (currentThread && currentRun) {
              void refreshAfterRun(currentThread, currentRun, generation, operation);
            } else {
              void refreshHistory();
            }
          },
          onAbort: () => {
            releaseSend(token);
          },
          onRecover: () => {
            if (!releaseSend(token)) return;
            if (!isCurrentView(generation)) return;
            void recoverRun(runIdRef.current, generation);
          },
          onError: (caught) => {
            if (!releaseSend(token)) return;
            if (!isCurrentView(generation)) return;
            setBusyError(messageOf(caught));
          },
        },
      );
    },
    [
      adopt,
      applyIncoming,
      isCurrentView,
      recoverRun,
      refreshAfterRun,
      refreshHistory,
      releaseSend,
      startSSE,
    ],
  );

  const cancel = useCallback(async () => {
    const runId = runIdRef.current;
    const generation = viewGenerationRef.current;
    if (!runId) return;
    try {
      const result = await cancelRun(runId);
      if (isCurrentView(generation) && runIdRef.current === runId) {
        const run = result.data;
        if (run) adopt({ ...stateRef.current, runStatus: run.status, pendingInterrupt: run.pending_interrupt ?? null });
        setNotice("订单或任务已取消；已提交的业务结果保持可核对。");
        const threadId = threadIdRef.current;
        if (threadId) await refreshAfterRun(threadId, runId, generation, runOperationRef.current);
      }
    } catch (caught) {
      if (isCurrentView(generation)) setBusyError(messageOf(caught));
    }
  }, [adopt, isCurrentView, refreshAfterRun]);

  const resume = useCallback(async (body: {
    interrupt_id: string; decision: "approve" | "reject" | "supplement" | "edit";
    expected_version: number | null; payload?: Record<string, unknown>; idempotency_key: string;
  }) => {
    const runId = runIdRef.current;
    const generation = viewGenerationRef.current;
    if (!runId || sendingRef.current) return;
    const token = { generation, id: ++sendSequenceRef.current };
    sendTokenRef.current = token;
    sendingRef.current = true;
    setSending(true);
    const operation = ++runOperationRef.current;
    setBusyError(null);
    try {
      const result = await resumeOrderRun(runId, body);
      if (sendTokenRef.current !== token || !isCurrentView(generation) || runIdRef.current !== runId) return;
      const run = result.data;
      if (run) adopt({ ...stateRef.current, runStatus: run.status, pendingInterrupt: run.pending_interrupt ?? null });
      const threadId = threadIdRef.current;
      if (threadId) await refreshAfterRun(threadId, runId, generation, operation);
      void recoverRun(runId, generation);
    } catch (caught) {
      if (sendTokenRef.current === token && isCurrentView(generation)) setBusyError(messageOf(caught));
    } finally {
      releaseSend(token);
    }
  }, [adopt, isCurrentView, recoverRun, refreshAfterRun, releaseSend]);

  const refresh = useCallback(async () => {
    const generation = invalidateView();
    setBusyError(null);
    await refreshHistory();
    if (!isCurrentView(generation)) return;
    const threadId = threadIdRef.current;
    if (threadId) await loadThread(threadId);
  }, [invalidateView, isCurrentView, loadThread, refreshHistory]);

  const selectThread = useCallback(
    async (threadId: string) => {
      // 即使当前已显示 B，点击 B 也必须使仍在 pending 的 A 失效。
      await loadThread(threadId);
    },
    [loadThread],
  );

  const newChat = useCallback(() => {
    invalidateView();
    setBusyError(null);
    setNotice(null);
    adopt(emptyChatState(null));
    syncUrl(null);
  }, [adopt, invalidateView]);

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
    resume,
    refresh,
    selectThread,
    newChat,
    dismissNotice: () => setNotice(null),
  };
}
