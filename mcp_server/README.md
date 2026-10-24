# mcp_server 业务 MCP（P03/P04）

## 职责

FastMCP Streamable HTTP 服务，保留 P03 的 9 个只读工具，并新增 P04 的 4 个受控草稿/订单工具。只读工具复用 P01 业务服务；订单写入口只走 P04 DraftService/MutationService：

`inventory_page`、`inventory_warning`、`inventory_get`、`supplier_query`、`supplier_get`、`part_search`、`part_query`、`quote_list`、`replenishment_preview`。

P04：`draft_prepare`、`order_create`、`order_get`、`order_page`。`order_create` 参数严格为 `draft_id`、`approval_id`、`idempotency_key`；金额和明细来自服务器草稿，未批准直调会报错且不留下 operation claim。

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

- P03 的九项只读 surface 保持独立；P04 仅增加上述四项。订单写入要求 owner-scoped approve，Mongo 事务原子处理订单、inbound、审批消费与幂等结果。
- 不复制补货规则；金额/库存派生值来自 P01 服务。
- 返回统一 `{ok,data,error,meta}`，meta 包含 data_source/as_of/scope/call_id。
- CI 使用真实 Mongo 与真实子进程 MCP；没有 Key 的 live 模型不在此服务内调用。
- `uv run pytest tests/integration/test_mcp_tools.py -q` 验证 13 项发现、原只读集合不变和未经批准的订单写入拒绝。
