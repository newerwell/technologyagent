"use client";

import { useCallback, useRef } from "react";

import { startChatStream } from "../lib/api";
import { IncompleteSSEFrameError, SSEParser } from "../lib/sse-parser";
import type { EventEnvelope } from "../lib/events";
import type { ChatRequest } from "../lib/events";

export type SSEHandlers = {
  onEvent: (event: EventEnvelope) => void;
  onEnd?: () => void;
  onError?: (error: unknown) => void;
  onAbort?: () => void;
  onRecover?: () => void;
};

export function useSSE() {
  const abortRef = useRef<AbortController | null>(null);

  const abort = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const start = useCallback(async (body: ChatRequest, handlers: SSEHandlers) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const isCurrent = () => abortRef.current === controller;
    try {
      const response = await startChatStream(body, { signal: controller.signal });
      if (!isCurrent()) return;
      if (!response.body) throw new Error("聊天流没有可读响应体");
      const reader = response.body.getReader();
      const parser = new SSEParser();
      let sawEnd = false;
      while (true) {
        const { done, value } = await reader.read();
        if (!isCurrent()) {
          await reader.cancel();
          return;
        }
        if (done) break;
        for (const event of parser.push(value)) {
          if (!isCurrent()) return;
          handlers.onEvent(event);
          if (event.type === "stream_end") sawEnd = true;
        }
      }
      parser.finish();
      if (!isCurrent()) return;
      if (sawEnd) handlers.onEnd?.();
      else handlers.onRecover?.();
    } catch (error) {
      if (!isCurrent()) return;
      if (controller.signal.aborted) {
        handlers.onAbort?.();
        return;
      }
      if (error instanceof IncompleteSSEFrameError) {
        handlers.onRecover?.();
        return;
      }
      handlers.onError?.(error);
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, []);

  return { start, abort };
}