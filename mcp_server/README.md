# mcp_server 只读业务 MCP（P03）

## 职责

FastMCP Streamable HTTP 服务，注册 9 个首批只读工具，复用 P01 的 CatalogService / InventoryService / ReplenishmentService：

`inventory_page`、`inventory_warning`、`inventory_get`、`supplier_query`、`supplier_get`、`part_search`、`part_query`、`quote_list`、`replenishment_preview`。

## 身份

- 工具 schema 不包含 owner/run/actor。
- API 为每个 run 签发短期 opaque token，存入 `mcp_sessions`（TTL）。
- MCP 从 `Authorization: Bearer` 解析 token 得到 owner/run/actor，再调用业务服务；无效 token 返回错误。

## 运行

```powershell
uv run python -m mcp_server.server
# GET http://127.0.0.1:9030/health
# POST http://127.0.0.1:9030/mcp
```

`start.ps1` 会启动/停止 MCP；API `/ready` 报告 MCP 端口不可达，但启动脚本要求 MCP health 通过。

## 边界

- 只读，不提供订单/审批/写工具。
- 不复制补货规则；金额/库存派生值来自 P01 服务。
- 返回统一 `{ok,data,error,meta}`，meta 包含 data_source/as_of/scope/call_id。
- CI 使用真实 Mongo 与真实子进程 MCP；没有 Key 的 live 模型不在此服务内调用。
