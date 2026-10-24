# hooks 对话状态

## 职责

- `useSSE`：POST 流、读取 bytes、`SSEParser` 解析；AbortController 只关闭观察，不取消后端 run。
- `useHistory`：本地会话列表；进入前 ensureLocalSession。
- `useChat`：发送/停止/刷新/切换、run+seq reducer、刷新后从 events 恢复、每 2 秒轮询直到终态；统一 viewGeneration 使 select/new/refresh/unmount 后的旧 load、恢复、流回调失效。
- `send` 在第一次 await 前同步占用 sendToken/sending；旧操作不能释放新发送。

## 关键边界

- 初始会话失败后可重试；历史加载前不丢 URL thread。
- 发送前确保本地 Cookie；同 thread 已有活跃 run 时服务端 409。
- 断线不 cancel；停止按钮调用 `POST /api/runs/{id}/cancel`。
- `useSSE` 每次连接有独立 AbortController；被替换连接的 end/abort/error 回调直接丢弃。
- 历史最终 message 与 token 以 message_id 合并，不重复拼接。

## 验证

`frontend/src/tests/{sse-parser,event-reducer}.test.ts` 与 `tests/e2e/chat-flow.spec.ts`。
