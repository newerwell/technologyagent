import type { ThreadView } from "../../lib/events";

type Props = {
  conversations: ThreadView[];
  activeThreadId: string | null;
  loading: boolean;
  onSelect: (threadId: string) => void;
  onNew: () => void;
};

export function ConversationList({ conversations, activeThreadId, loading, onSelect, onNew }: Props) {
  return (
    <aside className="chat-sidebar card" aria-label="会话历史">
      <div className="section-title">
        <div>
          <h2>会话</h2>
          <p className="hint">P02 · 本地持久化</p>
        </div>
        <button type="button" onClick={onNew} data-testid="new-chat-button">
          新对话
        </button>
      </div>
      {loading ? <p className="hint">加载中…</p> : null}
      <div className="conversation-list" data-testid="conversation-list">
        {conversations.length === 0 && !loading ? <p className="hint">还没有会话，发送第一条消息。</p> : null}
        {conversations.map((thread) => (
          <button
            key={thread.id}
            type="button"
            className={"conversation-item" + (thread.id === activeThreadId ? " active" : "")}
            onClick={() => onSelect(thread.id)}
            data-testid="conversation-item"
          >
            <strong>{thread.title || "未命名对话"}</strong>
            <small>{thread.active_run_id ? "运行中" : "已结束"} · {thread.id.slice(0, 12)}</small>
          </button>
        ))}
      </div>
    </aside>
  );
}
