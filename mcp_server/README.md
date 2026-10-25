# mcp_server 业务 MCP（P03/P04）

## 职责

FastMCP Streamable HTTP 服务，保留 P03 的 9 个只读工具，并新增 P04 的 4 个受控草稿/订单工具、P08参考23业务工具与`mutation_prepare`。查询复用共享服务与Provider；写工具需要通过服务端提案和人工决定，再进入业务MutationService：

`inventory_page`、`inventory_warning`、`inventory_get`、`supplier_query`、`supplier_get`、`part_search`、`part_query`、`quote_list`、`replenishment_preview`。

P04：`draft_prepare`、`order_create`、`order_get`、`order_page`。`order_create` 参数严格为 `draft_id`、`approval_id`、`idempotency_key`；金额和明细来自服务器草稿，未批准直调会报错且不留下 operation claim。

P08参考23名称以`P08_REFERENCE_TOOL_NAMES`固定。新增工具接受结构化`payload`，不接受owner/run字段；写调用若缺审批或审批action不匹配返回错误，不执行副作用。`mutation_prepare(action,payload)`只创建待审提案。订单页展示提案，只有显式用户决定后业务工具才可执行。收货时`inventory_inbound`可带order/receipt明细，内部走`InventoryMutationService.receive`单事务。

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

- P03 的九项只读 surface 保持独立；P04/P08按阶段追加。订单创建和本地收货均要求owner-scoped approve，Mongo事务原子保存业务事实与operation结果。
- 不复制补货规则；金额/库存派生值来自 P01 服务。
- 返回统一 `{ok,data,error,meta}`，meta 包含 data_source/as_of/scope/call_id。
- CI 使用真实 Mongo 与真实子进程 MCP；没有 Key 的 live 模型不在此服务内调用。
- `uv run pytest tests/integration/test_mcp_tools.py -q` 验证工具发现、P08 23名称覆盖、原P03事实和未批准写拒绝。
