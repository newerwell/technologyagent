# mcp_server 业务 MCP（P03/P04）

## 职责

FastMCP Streamable HTTP 服务，保留 P03 的 9 个只读工具，并新增 P04 的 4 个受控草稿/订单工具、P08参考23业务工具与`mutation_prepare`。查询复用共享服务与Provider；写工具需要通过服务端提案和人工决定，再进入业务MutationService：

`inventory_page`、`inventory_warning`、`inventory_get`、`supplier_query`、`supplier_get`、`part_search`、`part_query`、`quote_list`、`replenishment_preview`。

P04：`draft_prepare`、`order_create`、`order_get`、`order_page`。`order_create` 参数严格为 `draft_id`、`approval_id`、`idempotency_key`；金额和明细来自服务器草稿，未批准直调会报错且不留下 operation claim。

P09 remote_erp 只读：注册的 API 与 MCP 业务查询共用 `backend.app.integrations.provider_queries.ProviderQueries` 字段校验和分页聚合。记录缺必需字段、页集不完整或超过安全上限时返回明确错误，不读取 Mongo 作为替代结果。远程订单写能力、报价聚合和补货仍未启用；真实 ERP 验收 `not_run`。

P09 L01：独立`McpRuntime`从相同的受限`Settings.acceptance_business_now`构建`FixedClock`，用于Catalog报价有效期、补货预览、草稿及改单判价。MCP token TTL、调用时间与持久记录继续使用`SystemClock`。该配置只允许隔离的27028 `technologyagent_test_*`、local模式、全`local_seed`且无库存快照；正常运行默认不启用。

P08参考23项是15读、8写（不是23项只读）。名称由`P08_REFERENCE_TOOL_NAMES`固定；新增工具接受结构化`payload`，owner/run身份只能由Bearer token解析。`mutation_prepare(action,payload)`仅创建owner-scoped待审提案；写工具经显式批准后执行，按相同幂等键重放返回原结果，错误owner、未批准和过期版本不得产生业务效果。`order_create`复用P04事务服务，MCP装配时必须绑定模块Provider；订单页展示提案，只有显式用户决定后业务工具才可执行。收货时`inventory_inbound`可带order/receipt明细，内部走`InventoryMutationService.receive`单事务。

R7逐项的真实Streamable HTTP测试和数据库前后事实见[`evidence/P09-R7.md`](../evidence/P09-R7.md)。回归覆盖15项读工具的正常调用及不存在实体/状态输入、8项写工具的无批准拒绝、异owner拒绝、过期审批版本、批准执行与相同键重放；订单创建另复用P04批准/事务测试。此证据只证明合成`local_seed`与隔离`technologyagent_test_*`数据库，不证明真实ERP联调。真实ERP与远程写保持关闭。

## 身份

C04补齐23项非法结构的真实MCP调用，见[evidence/P09-C04.md](../evidence/P09-C04.md)。包装器保留参数类型校验，额外拒绝`payload=null`或缺失；不能将其转为空筛选。测试子进程日志写入独立临时文件，避免连续验证错误填满stderr管道导致夹具假超时。

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
- P09-fix3 分页报告契约：`inventory_page`、`inventory_warning`、`quote_list` 结果按完整筛选集生成`meta.snapshot_id`。适配器同时核对当前页与完整来源集；报告侧要求全部页的查询参数、source/scope、snapshot_id一致，且记录数/页码/实体ID无缺失或重复。`as_of`可逐次不同，不能单独作为跨调用快照键；来源数据变化会令snapshot_id变化或页核对失败。
- P09 R3：注册的`inventory_page`/`inventory_warning`业务分发成功后也必须绑定完整筛选集的snapshot_id；无法证明时返回`INCOMPLETE_SNAPSHOT`。全仓/指定仓位/物料范围由Agent传入的结构化约束统一用于数据集选取和报告核验。快照模式报价/补货明确拒绝时保留文件快照`data_source`、`as_of`和完整性metadata；不改变供应商Provider来源。证据见[evidence/P09-fix4](../evidence/P09-fix4.md)。
- CI 使用真实 Mongo 与真实子进程 MCP；没有 Key 的 live 模型不在此服务内调用。
- `uv run pytest tests/integration/test_mcp_tools.py -q` 验证工具发现、P08 23名称覆盖、原P03事实和未批准写拒绝。
