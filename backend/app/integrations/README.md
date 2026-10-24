# integrations 外部适配（P03）

## 职责

- `model.py`：OpenAI-compatible `/chat/completions` 流式适配，归一化 token、tool_call 增量、usage；60 秒超时，usage 缺失记录 null，不泄露 Key。
- `mcp.py`：每 run 独立 MCP Streamable HTTP client 与 Bearer header，发现工具/调用工具；不得共享全局 headers。
- 真实模型只在 `MODEL_MODE=live` 且配置 Key/name 时装配；fake 模式使用 ScriptedModel，不是 live。

## 调用

```python
model = build_model(settings)  # live 时返回 OpenAICompatibleModel，否则 None
registry = await McpRegistryFactory(url, tokens)(ctx)
result = await registry.invoke("inventory_page", {"warehouse_id": "W01"}, ctx, budget)
```

## 边界

- 适配器不直接写 SSE，不创建订单，不包含补货公式。
- 模型原始响应只保留脱敏摘要；工具参数中的 owner/run/token 字段不允许由模型注入。
- MCP server 不在线时工具调用返回明确失败，不能静默退化为空回答。
- live 需要用户提供 Key；没有 Key 不得声明 live_verified。
