import type { ChatMessage } from "../../lib/event-reducer";

type Props = { messages: ChatMessage[]; streaming: boolean };

export function MessageList({ messages, streaming }: Props) {
  if (messages.length === 0) {
    return (
      <div className="chat-empty" data-testid="chat-empty">
        <strong>开始一个本地模拟任务</strong>
        <p>当前是 FakeAgent：只输出示例 token 和只读假工具卡片，不调用真实模型，也不写业务数据。</p>
      </div>
    );
  }
  return (
    <div className="message-list" data-testid="message-list">
      {messages.map((message) => (
        <article key={message.id} className={"message message-" + message.role} data-message-id={message.id}>
          <header>
            <span>{message.role === "user" ? "你" : "FakeAgent"}</span>
            {message.streaming && message.role === "assistant" ? <span className="stream-caret">生成中</span> : null}
          </header>
          <p>{message.content}</p>
        </article>
      ))}
      {streaming ? <div className="stream-note">观察 SSE 中…</div> : null}
    </div>
  );
}
