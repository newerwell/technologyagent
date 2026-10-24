# hooks 对话状态

## 职责

- `useSSE`：POST 流、读取 bytes、`SSEParser` 解析；AbortController 只关闭观察，不取消后端 run。
- `useHistory`：本地会话列表；进入前 ensureLocalSession。
- `useChat`：发送/停止/刷新/切换、run+seq reducer、刷新后从 events 恢复、每 2 秒轮询直到终态；view generation 隔离会话切换，run-operation generation 使同一会话续发后旧 recover/终态刷新不能覆盖新 run。
- `send` 在第一次 await 前同步占用 sendToken/sending；旧操作不能释放新发送。

## 关键边界

- 初始会话失败后可重试；历史加载前不丢 URL thread。
- 发送前确保本地 Cookie；同 thread 已有活跃 run 时服务端 409。
- 断线不 cancel；停止按钮调用 `POST /api/runs/{id}/cancel`。
- `useSSE` 每次连接有独立 AbortController；被替换连接的 end/abort/error 回调直接丢弃。
- 历史最终 message 与 token 以 message_id 合并，不重复拼接。
- assistant 历史模式按各自 run 的持久 `run_started.model_mode` 显示；老数据无模式时显示“模式未知”，不从最新 run 推断。
- `run_finished` 与持久 `RunView` 同步 summary/committed_facts；刷新后仍能显示提交后的评审失败事实。结构化计划保留QueryEvidence供页面展示。

## 验证

`npm --prefix frontend run test -- --run src/hooks/useChat.test.tsx src/components/chat/MessageList.test.tsx` 与 `npm --prefix frontend run test:e2e`。
