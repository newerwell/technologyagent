# services 应用服务

## P09 review 输入事实

`OrderWorkflowService._build_order_review_fact_index` 是订单正文确定性核验和review-input回放共用的内部事实构造入口，数据只来自已读取的持久订单及`verification_facts`。每轮review事件关联当轮候选正文与原始请求；失败修订不重复审批或提交订单。

P09新增`TraceService`，按owner聚合持久模型/工具事件、阶段、审批、产物、数据源、错误码及业务效果；注册工具数量与run实际调用数量分开。Graph主模型、语义评审、订单意图抽取和订单说明修订都有稳定call_id/purpose及起止事件；trace计数以持久`model_calls`为实调用数，并显示事件覆盖度。usage缺项时只给known subtotal和missing count，完整usage为unknown/partial，不把小计展示为总量。`classify_recovery`为等待输入、已提交operation、processing租约、outcome_unknown、checkpoint和无checkpoint孤儿提供只读恢复分类；所有operation先整体检查，outcome_unknown优先于processing和succeeded，processing优先于succeeded。所有分类的`retry_business_write`均为false，写入结果必须先对账。

P09剩余工作R2：四处模型入口统一经`model_observation.collect_model_response`收集完整响应。每个真实尝试独立检查取消/期限、计入run模型预算并写入唯一`model_started/model_finished`；只有首个delta前的传输错误/超时最多额外重试一次，且共享首次计算的逻辑期限。失败尝试delta不会拼入成功正文；返回的usage只含安全token计数字段，未报告时为`None`。Graph工具事件绑定成功尝试的`successful_call_id`；`emit=None`仅禁用外部事件持久化，不禁用预算或观察流程。

DeepSeek 缓存计量由`cache_metrics.summarize_cache_events(events, expected_model_calls)`提供，按`(run_id, call_id)`配对并去重，仅把成功调用中三个非负整数且相加一致的缓存计数纳入命中率。`missing`与`invalid`分别保留；失败调用的usage单独计数，不混入成功命中率。`TraceService`在原有`model.usage`旁新增只读`model.cache`，按purpose与actor分组；旧事件缺元数据时仍可读，但全量命中率保持`null`。`collect_model_response`可接收固定`prompt_template_id`，并记录模型名、工具集摘要（适配器提供时）及从开始收流到首个token/tool-call的`first_output_ms`；不保存提示词或业务内容。

独立模型入口的提示内容与预算/校验保持不变，只补稳定模板标识：语义评审按受支持rubric类型区分`ta-semantic-review-1:<rubric>`，订单意图抽取为`ta-order-intent-extract-1`，订单说明修订为`ta-order-answer-revision-1`。结合运行的技能manifest和purpose解释trace；这些标识不代表缓存命中已经提高。


## P09 L01：业务判价时钟

`SystemClock`继续负责session/token TTL、run deadline/cancel、预算、operation lease及持久记录时间。只有显式配置`P09_ACCEPTANCE_BUSINESS_NOW`时，`FixedClock`才用于Catalog报价有效期、补货预览、草稿及改单判价；设置层要求`APP_MODE=local`、专用27028 `technologyagent_test_*`、四个Provider均为`local_seed`且未配置库存快照。默认保持空值，正常环境仍按真实时间判断。bootstrap把同一个Catalog/业务服务提供给API和fake registry；独立`McpRuntime`也使用同一判价时钟。验证：`uv run python -m pytest tests/unit/test_acceptance_business_clock.py tests/unit/test_p09_acceptance_environment.py tests/integration/test_fixture_business_transactions.py -q`。

## 职责

P00/P01/P02/P03/P04 服务：

- `SessionService`：生成随机 opaque token，以 HMAC-SHA256 保存摘要，设置 24 小时过期；`resolve()` 只接受有效未过期会话。
- `ReadinessService`：检查 DB ping、primary，执行一次真实事务写入并回滚，确认回滚后无残留，再汇总 model/mcp/sandbox 的 disabled 状态。
- `seeding.seed()`：校验 fixtures、manifest 与“未关闭订单剩余量 = inventory.inbound”对账，默认只补齐缺失的固定记录（`$setOnInsert`），不覆盖已有记录/version；`--reset` 只允许测试库。
- `baseline_repair.repair_p01_baseline()`：显式修正旧 I004/I006/I007 基线；默认 dry-run，`--apply` 在事务内执行，遇到修改过的库存或相关新增订单拒绝覆盖。
- `CatalogService`：目录/报价分页读取，报价 `is_valid` 由后端时间和供应商状态判定。
- `InventoryService`：库存分页、预警全量过滤后分页、全量汇总。
- P09 A2：`InventoryService.source_directory()`只读返回当前服务来源可见的仓位ID/名称与物料ID；seed由库存库查询，用户快照由适配器metadata及快照实体构造。remote_erp来源不回退本地Mongo来伪造目录，目录不可用时标记不可用并使显式仓位限定失败关闭。
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

P09补验收统一偏好保存终态：显式保存后必须由同一owner读回所有请求字段匹配，才发出通过的`PREFERENCE_PERSISTED`确定性review并以`completed`结束；RunView的持久review与`run_finished.review_passed`应同为true。该命令没有模型调用或业务计划。随后run必须在`plan.request_constraints.warehouse_ids`和实际查询参数中包含保存的默认仓库，最终通过的`NUMERIC_MATCH`与`REQUEST_CONSTRAINTS` review应绑定回答中的库存缺口与工具事实；订单/库存快照保持不变。

接口：`GET /api/preferences`查看，`PUT /api/preferences`明确保存/修改，`DELETE /api/preferences/{key}`删除。验证：`uv run pytest tests/integration/test_preferences.py -q`。

P07订单专家支持用户明确的多物料ID；每个ID由目录再次查询并验证启用状态，分析证据不是直接订单的必要前置。订单查询只通过order actor的`order_page`/`order_get`，不会准备草稿。分析答复使用最新同范围快照、具体计量单位和完整多仓证据；P03 oracle逐句核对失效报价的相反结论。审批仍保留在原run中；live证据按真实调用和数据库事实记录，不能用fake代替。

## P08 通用提案与库存事务

- `ApprovalService.request_mutation/resolve_mutation` 保存owner/run/action/payload hash/version与人工决定；决定本身不执行业务写。
- `BusinessMutationService.execute` 在事务内重新核对审批、operation租约和expected_version，支持供应商新增/状态、物料新增、库存手工收发、订单状态及submitted改单。订单新增物料金额从有效报价重算；改单按在途数量差同步库存。
- `InventoryMutationService.receive` 将Receipt、Movement、库存`on_hand/inbound/version`、订单`received_qty/status`、审批消费和operation结果放在同一Mongo事务；相同owner/provider/receipt_id重放返回原结果，冲突内容拒绝。
- P09 R6 `RemoteOperationService.execute(approval_id, action, payload, idempotency_key, ctx)`只接受显式启用的写action。新dispatch前按owner/action/决定核验提案，重新解析存储payload并用与`ApprovalService`一致的规范JSON SHA-256重算hash；`version`与`draft_version`必须是相同的正整数。Mongo事务内的审批CAS绑定ID、owner/action、approve/pending、核验hash与两个版本，并将这些核验值写入provider-scoped intent。成功operation的相同键重放仍先返回原持久结果；新operation只有在事务提交后才可置dispatch标记并POST。相同key异payload或异审批冲突。
- remote dispatch marker持久提交后才发送一次POST；超时、HTTP错误、响应损坏、结果保存失败均保留`outcome_unknown`，后续不能由重试提交。`ReconciliationService`识别remote operation后只按原provider correlation lookup；404、超时、关联号或状态未验证均保持unknown且`retry_business_write=false`。ErpClient内存guard只是附加保护，不是持久幂等保证。
- 生产`ErpProvider.write_actions`仍为空集合，真实ERP不执行写入。远程栅栏只用隔离Mongo和持续loopback HTTP模拟器验证；真实ERP F15/F16仍`not_run`。

限制：真实ERP没有配置的环境不会执行；外部字段、分页和状态映射以`docs/erp-mapping.md`为准，未观察到的字段仍为unknown。验证：`uv run pytest tests/integration/test_business_mutations.py tests/integration/test_inventory_receipts.py tests/integration/test_provider_contract.py -q`。
# P08 改单批准事实

`order_update` 提案在创建时保存每条报价的服务端快照哈希；批准后的事务再次读取报价并比较全部计价/交期/有效期字段。任一报价变化返回 `STALE_APPROVAL`，不修改订单或 inbound，用户需重新准备并批准提案。旧格式改单提案缺快照时失败关闭。

## P09 正式报告与订单说明结算

`AnalysisArtifactService.generate_report(dataset, format, ctx)`从受权只读结果构造报告、登记并发布格式/范围/来源与正文SHA-256。Agent执行器必须用同一授权数据集重建预期正文、重新打开存储产物并逐字节核验，之后才写`report_verified`；分页库存的页集和快照不完整时拒绝生成。`OrderWorkflowService._settle`在原订单事务提交后只查询持久订单/operation/审批，最多2次纯文本修订且每轮做字段和金额硬校验，绝不再次调用订单写服务。验证：`uv run pytest tests/integration/test_analysis_artifact_flow.py tests/integration/test_order_review_loop.py tests/integration/test_order_settlement_failures.py -q`。

## P09 最终补修：停用物料预览

`ReplenishmentService.preview`保留停用物料经核验的库存可用量、预计量、缺口和预警，但重建经`PreviewLine`验证的结果，清空报价候选和采购金额并标注`part_inactive`。即使库存记录不存在，也同时报告`inventory`与`part_inactive`；不补造库存事实，仍保持不可采购。MCP工具说明要求Agent把停用标记解释为“物料已停用”，数据页也显示相同中文原因。`DraftService.prepare`原有停用拒绝（409）保持不变。验证：`tests/unit/test_replenishment_service.py`、`tests/unit/test_replenishment.py`及前端`ReplenishmentPreview.test.tsx`。

## P09最终补修：订单提交事实与正文结算

`MutationService`在订单批准事务里从当时的启用物料、已核验报价和原run意图生成`verification_facts`，并与订单、inbound、审批消费及operation结果同事务保存。快照记录提交时单位、数量、仓库、quote/supplier、报价交期与观察时间，以及已保存的用户最大交期约束；缺失单位保持缺失。`OrderRepository`不把内部核验快照暴露到普通订单API。`OrderWorkflowService._settle`只用此快照核验数量、金额、交期说明和实际收货状态，不再向当前物料目录借用单位；正文必须覆盖单号、数量和总额，有保存的交期要求时还要区分用户要求与批准报价交期。fake模式直接从这些持久事实生成初始说明，不依赖模型改写。肯定的完成收货、签收或入库表述须与订单收货状态一致；明确否定的“报价交期不代表已经到货”不会误判。语义评审仅收到白名单快照字段。提交后结算最多进行2次纯正文修订、总计最多3次检查；每轮确定性数值/范围/来源检查先通过才进入语义检查，未通过时终态明确保留已提交事实，不重放订单。定向单测：`tests/unit/test_order_review_bounds.py`、`tests/unit/test_order_verification_persistence.py`、`tests/unit/test_semantic_review.py`；Mongo事务集成：`tests/integration/test_order_review_loop.py`和`tests/integration/test_order_settlement_failures.py`，运行需`ta-rs`副本集。

## P09 L03：按命题和订单范围核验收货说明

`_unnegated_receipt_claims`先按句号、分号、换行和“但/但是/然而/不过”切分命题，再区分“交期不表示/不意味着/不代表已到货”的推论否定与同一命题里的直接否定。前句“尚未收货”不能豁免后句“已到货”；逗号后的转折肯定也必须核验。`_receipt_claims_for_order`按单号绑定收货主张；多订单里未带单号的肯定主张视为范围不明，对未收货订单失败关闭。提交后异常的终态说明保留单号并明确“说明评审未通过或未完成”，且不会自动重放订单写。定向/Mongo结果见`evidence/P09-L03.md`。
