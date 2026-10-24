"use client";

import { useState } from "react";

type Props = {
  busy: boolean;
  sending: boolean;
  canCancel: boolean;
  onSend: (value: string) => void;
  onCancel: () => void;
};

export function Composer({ busy, sending, canCancel, onSend, onCancel }: Props) {
  const [value, setValue] = useState("");

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const text = value.trim();
    if (!text || busy) return;
    setValue("");
    onSend(text);
  }

  return (
    <form className="composer" onSubmit={submit}>
      <label className="composer-label" htmlFor="chat-input">
        消息
      </label>
      <textarea
        id="chat-input"
        data-testid="chat-input"
        value={value}
        rows={3}
        maxLength={4000}
        placeholder="例如：测试流式输出"
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit(event);
          }
        }}
      />
      <div className="composer-actions">
        <span className="hint">FakeAgent · 不接真实模型 · 不写业务数据</span>
        <div className="button-row">
          {canCancel ? (
            <button type="button" className="danger" data-testid="stop-button" onClick={onCancel}>
              停止
            </button>
          ) : null}
          <button type="submit" data-testid="send-button" disabled={busy || value.trim() === ""}>
            {busy ? "执行中…" : "发送"}
          </button>
        </div>
      </div>
    </form>
  );
}
