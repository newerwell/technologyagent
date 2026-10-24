"use client";

import { useState } from "react";

import { useChat } from "../../hooks/useChat";
import { ConversationList } from "../sidebar/ConversationList";
import { Composer } from "./Composer";
import { MessageList } from "./MessageList";
import { ToolCards } from "./ToolCards";

export function ChatPage() {
  const chat = useChat();
  const [draftThreadId, setDraftThreadId] = useState<string | null>(null);
  const activeThread = chat.state.threadId ?? draftThreadId;
  const modelLabel = chat.state.modelMode === "live" ? "Live Model" : "ScriptedModel";
  const modeText = chat.state.modelMode === "live" ? "live" : "fake";

  return (
    <main className="shell chat-shell">
      <header className="hero data-hero">
        <div>
          <p className="eyebrow">P03 · 只读采购助手</p>
          <h1>有工具依据的对话</h1>
          <p className="lede">
            模型通过受控只读工具查询本地库存、供应商、报价和补货规则；
            页面显示工具参数、来源与持久化 SSE。当前模式：{modelLabel}（model_mode={modeText}），不写订单。
          </p>
        </div>
        <div className="hero-actions">
          <a className="nav-link" href="/">
            返回工程状态
          </a>
          <a className="nav-link" href="/data">
            业务数据
          </a>
          <span className="badge badge-muted" data-testid="fake-badge">
            {modelLabel} · model_mode={modeText}
          </span>
          <button type="button" onClick={() => void chat.refresh()} disabled={chat.sending}>
            刷新 / 恢复
          </button>
        </div>
      </header>

      {chat.error ? (
        <section className="alert" role="alert">
          <strong>对话操作失败</strong>
          <p>{chat.error}</p>
          <p className="hint">已有事件仍可从持久化历史恢复；刷新只会重连观察，不会取消后台任务。</p>
        </section>
      ) : null}
      {chat.notice ? (
        <section className="notice" role="status">
          {chat.notice}
          <button type="button" onClick={chat.dismissNotice}>关闭</button>
        </section>
      ) : null}

      <div className="chat-layout">
        <ConversationList
          conversations={chat.conversations}
          activeThreadId={activeThread}
          loading={chat.historyLoading}
          onSelect={(threadId) => {
            setDraftThreadId(threadId);
            void chat.selectThread(threadId);
          }}
          onNew={() => {
            setDraftThreadId(null);
            chat.newChat();
          }}
        />

        <section className="card chat-main" aria-label="对话">
          <div className="chat-toolbar">
            <div>
              <span className="pill">thread {chat.state.threadId?.slice(0, 16) ?? "未开始"}</span>
              <span className="pill">run {chat.state.runId?.slice(0, 16) ?? "-"}</span>
              <span className="pill">status {chat.state.runStatus ?? "idle"}</span>
            </div>
            <span className="badge badge-muted">{modelLabel} · {modeText === "live" ? "真实模型" : "离线脚本"}</span>
          </div>

          <MessageList messages={chat.state.messages} streaming={chat.busy} modelLabel={modelLabel} />
          <ToolCards tools={chat.state.tools} />

          <Composer
            busy={chat.busy}
            sending={chat.sending}
            canCancel={chat.busy && Boolean(chat.state.runId)}
            onSend={(value) => void chat.send(value)}
            onCancel={() => void chat.cancel()}
          />
        </section>
      </div>

      <footer className="footer">
        <span>SSE: POST /api/chat/stream · 事件按 run+seq 去重</span>
        <span>历史: GET /api/conversations · 查询: GET /api/runs/{"{id}"}/events</span>
      </footer>
    </main>
  );
}