# components/chat 对话 UI

## 职责

- `ChatPage`：组合会话列表、消息、工具卡片和输入框；按 run_started.model_mode 显示 ScriptedModel/Live Model。
- `MessageList`：user/assistant 消息，按 message_id 渲染；流式消息显示“生成中”。
- `ToolCards`：显示 call_id 配对的只读工具参数、状态、结果、来源。
- `Composer`：发送/停止；输入长度 4000，Enter 发送、Shift+Enter 换行。

## 状态来源

`hooks/useChat.ts` 管理 SSE 观察、历史恢复、2 秒轮询、取消和 URL thread 参数；组件不自行计算事件去重或补货公式。

## 边界

- fake 模式明确为 ScriptedModel；工具结果来自 local_seed/MCP，不宣称订单写入。
- 刷新页面从 URL thread 恢复；停止只发 cancel，不靠断开 SSE。
- 会话历史来自服务端持久消息，token 丢帧不应造成重复 assistant 消息。

## 验证

```powershell
npm --prefix frontend run test -- --run
npm --prefix frontend run test:e2e
```