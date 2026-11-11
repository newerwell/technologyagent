# integrations 外部适配（P03）

本地文件库存：`inventory_snapshot.py` 读取 `INVENTORY_SNAPSHOT_PATH` 指向的本项目副本，供 API、MCP 和本地工具共用；库存与随带物料使用 local_snapshot。源 total/pages 与实际记录数分开保留，分页按实际保存记录计算；缺失目标库存、预留、在途保持未知。文件损坏明确报错，不回退其他数据源；库存副本不支持业务写入、供应商报价或目标补货推算。配置和限制见根目录 `data/README.md`。验证：`pytest tests/unit/test_inventory_snapshot.py tests/integration/test_inventory_snapshot_routes.py`。

## 职责

- `model.py`：OpenAI-compatible `/chat/completions` 流式适配，保留 tool_call index 并归一化 token、调用片段、usage；要求 `[DONE]` 或 `finish_reason` 结束，提前 EOF/成功响应内容解码错误返回 `MODEL_PROTOCOL_ERROR`。HTTP非2xx优先作为`MODEL_PROVIDER_ERROR`，不读取或回传错误正文，避免正文超时、损坏内容或敏感信息覆盖状态。
- `model_observation.py`（应用服务）：将传输中断/超时与模型协议错误分开；协议错误、HTTP状态错误、收到任一delta后的断流不重试。传输类异常仅在首delta前重试一次，由调用方共享预算/总时限并记录每次尝试。逻辑模型期限最多60秒，同时受较短调用期限与run剩余时间约束；一次重试共享同一截止时间。
- 发给模型的工具定义只来自本次`registry.available(ctx)`授权列表；适配器按名称排序，并递归排序schema对象键、保留数组次序。`toolset_id_for()`对最终规范化工具JSON返回`sha256:`摘要，空工具集也有固定摘要。它不会缓存MCP发现结果，也不包含owner、token或工具结果。
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

## P08 Provider 与 P09 远程只读查询

- `business_provider.py` 定义来源与能力边界；`local_provider.py` 支持 `local_seed` 与只读 `local_snapshot`；`erp_provider.py` 只调用明确声明的远程读取操作。四个业务模块独立读取 `SUPPLIERS_DATA_SOURCE`、`PARTS_DATA_SOURCE`、`INVENTORY_DATA_SOURCE`、`ORDERS_DATA_SOURCE`。
- `provider_queries.py` 是 API 与 MCP 共用的远程只读查询入口。它将既有字段映射后的记录校验为 `Part`、`Supplier`、`InventoryView`、`PurchaseOrder` DTO；缺字段、类型/业务校验失败、页码/页大小/页数/total矛盾、缺页、重复实体或记录数不符时明确失败，不从 Mongo 回退。列表请求收齐并校验完整页集后才返回调用方要求的页。每次 `page`/`get`/`all_records` 先固定一个不超过服务时限与run剩余预算的单一deadline；无剩余预算时使用服务时限，非有限或非正值在发请求前失败。等待provider也由该剩余时间实际限时并取消，响应返回、DTO映射、聚合和最终Page构造后再次核时；最后一页迟到也返回503 `DEPENDENCY_UNAVAILABLE`，不能被当作完整结果。每次HTTP请求收到同一逻辑读取剩余时间，MCP外层run deadline继续约束整个工具调用。远程报价/补货没有完整来源和工具映射，仍明确不支持。
- `erp/mappings.py`将库存ID和数量别名集中声明：`id`优先于`inventory_id`，`on_hand`优先于`quantity`、`stock_qty`。`map_inventory`、缺失字段检查和`ProviderQueries`原始整数校验共用该声明；显式成员检查保留合法0，不推断其他ERP字段。无ID/数量来源、null、bool冒充整数、负计数、非正版本均关闭失败；不会为快照或远程记录补造单位、目标库存。
- `erp/client.py` 的读取最多3次尝试并受剩余时限约束；远程写入能力保持关闭，写操作的未知结果不能重发。
- `erp/mappings.py` 金额以 `Decimal` 精确换元；必需字段保持缺失错误，不补0或业务默认值。报价补充字段MOQ/交期/有效期未提供时仍为 `None`；未知订单状态不进入有效订单 DTO。
- `docs/erp-mapping.md` 列出当前映射与本地 HTTP 模拟器边界。模拟器仅证明本地映射/分页代码，不证明真实ERP端点或字段已经验证。

## P09 R6 持久远程操作屏障

- `ErpClient.write`只做单次HTTP尝试；异常返回`ErpOutcomeUnknown`。同进程unknown集合只是防误用的次级保护，持久唯一性由`RemoteOperationService`和`OperationRepository`保证。
- `RemoteOperationService`从已配置endpoint规范化provider scope；审批和operation intent在同一Mongo事务绑定后，持久dispatch标记确认才允许一次POST。不同owner/provider/action彼此隔离；operation存在时不会因lease过期或服务重启再次POST。
- `ErpProvider.mutate`不信任`approved=True`，必须委托持久operation服务并携服务端RequestContext、审批ID与幂等键。Bootstrap写action集合为空，MCP没有已验证远程写能力；真实ERP保持关闭。
- `ReconciliationService`对远程operation只访问对应provider lookup。普通404、网络错误、未匹配关联号或未确认状态均保留`outcome_unknown`，不根据本地订单缺失判断是否可重试。
- 本地HTTP模拟器与真实副本集Mongo回归：`tests/integration/test_remote_operations_r6.py`；真实ERP写能力F15/F16仍`not_run`。

验证：本模块常规回归 `uv run python -m pytest tests/unit/test_provider_queries.py tests/unit/test_p08_erp_adapter.py tests/integration/test_provider_contract.py tests/integration/test_provider_switching.py tests/integration/test_provider_queries_r5.py -q -rs`。C01期限证据见`evidence/P09-C01.md`；C02库存别名和REST/MCP一致性见`evidence/P09-C02.md`。真实ERP保持`not_run`。
