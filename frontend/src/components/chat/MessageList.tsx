import type { ChatMessage } from "../../lib/event-reducer";

type Props = { messages: ChatMessage[]; streaming: boolean; modelLabel: string };

export function MessageList({ messages, streaming, modelLabel }: Props) {
  if (messages.length === 0) {
    return (
      <div className="chat-empty" data-testid="chat-empty">
        <strong>开始一个本地只读任务</strong>
        <p>当前执行器为 {modelLabel}：通过受控只读工具查询本地业务数据，不写订单。</p>
      </div>
    );
  }
  return (
    <div className="message-list" data-testid="message-list">
      {messages.map((message) => (
        <article key={message.id} className={"message message-" + message.role} data-message-id={message.id}>
          <header>
            <span>{message.role === "user" ? "你" : message.modelMode === "live" ? "Live Model" : message.modelMode === "fake" ? "ScriptedModel" : "模式未知"}</span>
            {message.streaming && message.role === "assistant" ? <span className="stream-caret">生成中</span> : null}
          </header>
          <p>{message.content}</p>
        </article>
      ))}
      {streaming ? <div className="stream-note">观察 SSE 中…</div> : null}
    </div>
  );
}
