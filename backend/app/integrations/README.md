# integrations 外部适配（P03）

## 职责

- `model.py`：OpenAI-compatible `/chat/completions` 流式适配，保留 tool_call index 并归一化 token、调用片段、usage；要求 `[DONE]` 或 `finish_reason` 结束，提前 EOF 返回 `MODEL_PROTOCOL_ERROR`。
- `mcp.py`：每 run 独立 MCP Streamable HTTP client 与 Bearer header，发现工具/调用工具；发现失败、取消或半初始化时由工厂清理，成功返回后由 executor 关闭；不得共享全局 headers。
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
- 单次模型/工具时限受剩余 run 总时限限制；清理错误不覆盖原始建立/发现异常。
- live 需要用户提供 Key；没有 Key 不得声明 live_verified。

## P08 Provider 与 ERP 适配

- `business_provider.py` 定义能力声明；`local_provider.py` 支持 `local_seed` 与只读 `local_snapshot`；`erp_provider.py` 按明确 capability 调用远程ERP。四个业务模块可分别配置 `SUPPLIERS_DATA_SOURCE`、`PARTS_DATA_SOURCE`、`INVENTORY_DATA_SOURCE`、`ORDERS_DATA_SOURCE`；配置远程源但未提供ERP客户端时失败关闭，不回退本地。
- `erp/client.py` 提供 `read/write/lookup`。读取最多3次请求且遵守调用方预算；写入只请求一次并在传输超时抛 `OUTCOME_UNKNOWN`。普通404不是“未产生副作用”的证明。
- `erp/mappings.py` 使用 `Decimal` 精确换元；缺MOQ/交期/有效期保持 `None` 并列入 `missing_fields`；未知状态保留 `raw_status`、映射为 `unknown`，禁止作为可写状态。
- `docs/erp-mapping.md` 记录本地映射样例与真实接口未验证项；不得把HTTP模拟器结果报告为真实ERP联调。

验证：`uv run pytest tests/unit/test_p08_erp_adapter.py tests/integration/test_provider_contract.py -q`。真实ERP须在明确配置 `ERP_ENVIRONMENT=test`、隔离测试库和测试账号后另行运行 `tests/live/test_erp_*.py`。
