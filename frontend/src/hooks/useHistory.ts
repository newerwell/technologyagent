"use client";

import { useCallback, useEffect, useState } from "react";

import { ensureLocalSession, listConversations } from "../lib/api";
import type { ThreadView } from "../lib/events";

export function useHistory() {
  const [conversations, setConversations] = useState<ThreadView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      await ensureLocalSession();
      const envelope = await listConversations();
      setConversations(envelope.data ?? []);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "会话列表加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { conversations, loading, error, refresh };
}
