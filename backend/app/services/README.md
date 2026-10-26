# services 应用服务

P09新增`TraceService`，按owner聚合持久模型/工具事件、阶段、审批、产物、数据源、错误码及业务效果；注册工具数量与run实际调用数量分开。Graph主模型、语义评审、订单意图抽取和订单说明修订都有稳定call_id/purpose及起止事件；trace计数以持久`model_calls`为实调用数，并显示事件覆盖度。usage缺项时只给known subtotal和missing count，完整usage为unknown/partial，不把小计展示为总量。`classify_recovery`为等待输入、已提交operation、processing租约、outcome_unknown、checkpoint和无checkpoint孤儿提供只读恢复分类；所有operation先整体检查，outcome_unknown优先于processing和succeeded，processing优先于succeeded。所有分类的`retry_business_write`均为false，写入结果必须先对账。

## 职责

P00/P01/P02/P03/P04 服务：

- `SessionService`：生成随机 opaque token，以 HMAC-SHA256 保存摘要，设置 24 小时过期；`resolve()` 只接受有效未过期会话。
- `ReadinessService`：检查 DB ping、primary，执行一次真实事务写入并回滚，确认回滚后无残留，再汇总 model/mcp/sandbox 的 disabled 状态。
- `seeding.seed()`：校验 fixtures、manifest 与“未关闭订单剩余量 = inventory.inbound”对账，默认只补齐缺失的固定记录（`$setOnInsert`），不覆盖已有记录/version；`--reset` 只允许测试库。
- `baseline_repair.repair_p01_baseline()`：显式修正旧 I004/I006/I007 基线；默认 dry-run，`--apply` 在事务内执行，遇到修改过的库存或相关新增订单拒绝覆盖。
- `CatalogService`：目录/报价分页读取，报价 `is_valid` 由后端时间和供应商状态判定。
- `InventoryService`：库存分页、预警全量过滤后分页、全量汇总。
- `ReplenishmentService`：一次拉齐 parts/inventory/quotes/suppliers，调用纯函数，返回 snapshot_versions 与 SourceRef。
- `RunService`：thread/run/message/event 事务、request_id 幂等、seq 原子递增、终态与启动孤儿失败恢复；删除先条件认领 thread（active_run_id=None 且 deleting!=true），与创建认领互斥。
- `RunService.create_or_get` 在每次事务/竞争重试重查 owner/request_id/hash，返回 `(RunView, just_created)`。
- `McpTokenService`：每 run 签发短期 opaque token，保存摘要；MCP 服务端解析 owner/run/actor。
- `ChatService`：后台任务管理器 + 注入的 AgentExecutor（P03 bootstrap 为 GraphExecutor）；budget 先于 run_started 注册，执行器启动前同步持久 cancel_requested；SSE 只观察持久事件，观察连接关闭不取消任务。
- `DraftService`：使用服务端补货预览创建草稿；不猜缺失字段；expected_version CAS 更新并同事务 supersede 旧审批。
- `ApprovalService`：人工决定绑定 owner/run/draft/version/hash；决定键与payload hash持久化，重复相同决定返回原结果，冲突决定被拒绝；工作流草稿只能由其所属run恢复。
- `MutationService`：检查成功幂等重放，预拒绝未批准调用；事务内重新验证零件启用状态、租约归属、报价、供应商、库存版本和取消栅栏，并一起写订单、inbound、草稿/审批消费和幂等结果。
- P09-F03：`MutationService.execute`是订单工作流/API共用的最终本地事务入口，按订单、库存、物料和供应商Provider重新检查写能力；`OrderWorkflowService.resume`及启动恢复在approve前也重查同一Provider。local_snapshot/remote_erp拒绝写入并保留waiting审批，remote不可用不会回退local_seed。
- `OrderWorkflowService`：使用 Mongo checkpointer 恢复同 thread/run 的固定版本节点；resume决定先持久化再恢复，启动恢复同时对照checkpoint与已提交operation；等待中取消会释放thread，已提交业务事实保留。
- P05补修：每个order_create operation带所属run_id；订单提交后review/revision失败也写入唯一终态和订单事实。历史决定按键保存canonical请求hash与结果快照，旧决定可在后续决定完成后重放；等待审批取消以waiting状态CAS竞争，摘要按已提交operation实际生成。
- Run的 `active_seconds_used` 在进入人工等待时累加，等待不计时；resume重开活跃计时，结算时继续累计。模型/工具调用计数留在同一Run文档中。
- `DraftService`：订单页、聊天历史都返回草稿所属run与待处理中断；工作流草稿跨页面统一经run resume编辑或决定，独立草稿走独立入口。
- `ReconciliationService`：只读核对操作状态和 operation_id 订单；已提交返回原结果，超时租约且没有订单时允许使用原幂等键重试，不自动补写。
- `ArtifactService`：P06生成artifact_id与storage key，校验扩展名/MIME/签名/UTF-8/JSON/大小后原子写入；下载/预览按当前owner查元数据与文件，不接受磁盘路径。
- `ReadinessService`：探测Docker镜像和daemon；沙箱不可用只关闭分析执行能力，不影响普通只读业务查询。
- SSE 观察在终态后继续排空到 last_seq，不因一次空 events 查询漏 stream_end。

## P09 通用提案确认与恢复

- `ApprovalService.request_mutation`为改单从数据库读取订单、物料单位和有效报价，保存旧/新明细、单价、行额和总额快照；订单页和聊天审批卡展示同一服务端事实，执行仍按报价hash与订单版本重查。
- `mutation_prepare`成功后，Graph停止后续模型/工具步骤并把原run写为持久`waiting_input`，中断保存approval/proposal/action/canonical payload及事实快照。刷新后通过原run的resume入口决定，不从浏览器提交可替换的业务payload。
- 原run决定要求owner、run、interrupt、版本和幂等键一致；批准前与实际执行前均检查Provider能力。业务MutationService只消费持久proposal payload。决定/operation使用幂等键；进程在决定记录后中断时，启动恢复按`workflow_kind=mutation_proposal`对同一记录重放对账，不重复业务效果。
- 本地确定性验收覆盖Graph创建中断、Mongo持久状态、批准/拒绝、重复恢复与同run归属。remote intent/对账和旧v1图版本隔离仍不在本修复中。

## P06与订单事实补修

- `AnalysisArtifactService`只从当前run授权的只读数据集生成固定报告/图表；结构化来源及观察时间随产物与报告保留。发布事件发生在内容校验、文件原子写入和元数据登记之后。普通报告不依赖Docker；图表与分析代码依赖受控容器。
- `ArtifactService.list_for_thread`先校验会话owner，再聚合该会话所有run的ready产物，响应不含storage_key；下载仍通过artifact_id按owner重新授权。
- 订单最终正文每轮都按已提交的持久订单检查显式数量、分/元金额，硬失败不能被语义评审覆盖；修订stream受run剩余时限限制并每100ms检查取消/截止时间。崩溃恢复从持久 `resume_request.idempotency_key` 记录决定结果，使旧决定可返回原快照。
- P03事实绑定将Markdown表头固定到表格分隔线之前的header，并把supplier_id纳入scope；P03/P05 live验收统一要求真实终态、工具事实及答案匹配，任何live pytest skip均失败。

## 公开接口

```python
record, raw_token = await session_service.create_local()
record = await session_service.resolve(raw_token)
result = await readiness_service.check()
report = await repair_p01_baseline(mongo, apply=False)  # 默认 dry-run
run = await run_service.create(None, "hello", "request-1", ctx)
await chat_service.start(None, "hello", "request-1", ctx)
result = await mutation_service.execute(draft_id, approval_id, "key-1", ctx)
check = await reconciliation_service.reconcile(result["operation_id"], ctx)
```

## 边界

- 服务不读取请求体身份；owner 由 SessionService 固定为 `local-owner`。
- P01 不包含聊天、模型、审批或订单执行；补货公式只在 `domain/replenishment.py`。
- P03 生产 fake 模式使用 ScriptedModel + 本地只读工具；live 模式使用 OpenAI-compatible ModelPort + MCP；两者同一 GraphExecutor。
- P02 启动恢复只把遗留非终态 run 标 failed/PROCESS_RESTARTED，不是 checkpoint 恢复。
- `/ready` 的事务探针使用独立随机 `_id`，回滚后断言文档数为 0。
- seed 默认不删除也不覆盖数据；`--reset` 对非 `technologyagent_test_*` 数据库直接失败。
- 旧基线修正不是 API 启动迁移，也不接受 `--reset`；冲突时报告并停止。
- FakeAgent 的 token/工具事件只用于协议验收，不调用真实模型或业务写入。
- order_create 不接受模型金额；只接收服务器草稿、人工批准和幂等键。写入要求 Mongo replica-set 事务。模型意图抽取先认领幂等run，并计入同一run的模型次数、取消检查和活跃时限。
- P04 回归：`uv run pytest tests/integration/test_drafts.py tests/integration/test_checkpoint_resume.py tests/integration/test_order_idempotency.py -q`。

## P07 显式偏好

`PreferenceService` 只支持 `default_warehouse`、`preferred_supplier`、`max_lead_days`。API或聊天写入都必须有用户明确“记住”意图；服务校验仓库存在、供应商仍启用、交期为0–365整数，并按owner保存。父run从同一服务读取当前owner偏好，和本轮请求合并后携来源传到专家；本轮优先，不自动记住。本轮明确清除与字段缺失分开处理，偏好不绕过报价有效性或审批。

接口：`GET /api/preferences`查看，`PUT /api/preferences`明确保存/修改，`DELETE /api/preferences/{key}`删除。验证：`uv run pytest tests/integration/test_preferences.py -q`。

P07订单专家支持用户明确的多物料ID；每个ID由目录再次查询并验证启用状态，分析证据不是直接订单的必要前置。订单查询只通过order actor的`order_page`/`order_get`，不会准备草稿。分析答复使用最新同范围快照、具体计量单位和完整多仓证据；P03 oracle逐句核对失效报价的相反结论。审批仍保留在原run中；live证据按真实调用和数据库事实记录，不能用fake代替。

## P08 通用提案与库存事务

- `ApprovalService.request_mutation/resolve_mutation` 保存owner/run/action/payload hash/version与人工决定；决定本身不执行业务写。
- `BusinessMutationService.execute` 在事务内重新核对审批、operation租约和expected_version，支持供应商新增/状态、物料新增、库存手工收发、订单状态及submitted改单。订单新增物料金额从有效报价重算；改单按在途数量差同步库存。
- `InventoryMutationService.receive` 将Receipt、Movement、库存`on_hand/inbound/version`、订单`received_qty/status`、审批消费和operation结果放在同一Mongo事务；相同owner/provider/receipt_id重放返回原结果，冲突内容拒绝。
- `ErpClient`远程写没有自动重试；HTTP write超时必须先按原关联号对账，普通404不可据此重发。

限制：真实ERP没有配置的环境不会执行；外部字段、分页和状态映射以`docs/erp-mapping.md`为准，未观察到的字段仍为unknown。验证：`uv run pytest tests/integration/test_business_mutations.py tests/integration/test_inventory_receipts.py tests/integration/test_provider_contract.py -q`。
# P08 改单批准事实

`order_update` 提案在创建时保存每条报价的服务端快照哈希；批准后的事务再次读取报价并比较全部计价/交期/有效期字段。任一报价变化返回 `STALE_APPROVAL`，不修改订单或 inbound，用户需重新准备并批准提案。旧格式改单提案缺快照时失败关闭。
