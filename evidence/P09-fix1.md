# P09-fix1 修复与补验收记录

日期：2026-10-26。范围为 P09-followup F01–F09 与 P09 前置残留；不开始 P10。该记录按独立任务追加，旧阶段标签不移动。

## F01：F12 判分与 live attempt 门禁

- 历史证据 `evidence/P09/live/F12-preference-complete-traces.json` 保持原样。只读统计确认 3 组、9 次 query、9 个旧 `passed=true`；9 次终态均为 `failed`，9 次终态 `review_passed=false`。旧分数是验收代码缺陷的证据，不代表通过。
- 新增验收 oracle：设置偏好和后续查询分别校验 live 模式、完整连续事件、completed 终态、review、无 error、owner偏好持久化、W01成功结构化工具事实、P001/55套最终回答与业务库前后快照。
- 新增 wrapper 回归：pytest 全 skip、空summary、部分 skip 均拒绝；子进程 timeout留下失败记录，同一逻辑 attempt 再执行生成另一个证据文件，不覆盖前次。每个 attempt 在 seed 前记录开始时间，并原子写入轨迹。
- 定向检查：`uv run pytest tests/unit/test_final_acceptance_oracle.py tests/integration/test_p09_live_gate.py -q`，exit 0，9 passed。此处是确定性测试，不是真实模型验收。
- 新的 P09 live 批次尚未运行；不把历史轨迹重放或现有 fake 运行记作新 live 通过。其余 P09 必需门槛尚未关闭，不创建 `phase-p09`。

## F02：跨来源业务事实身份

- 红测复现：`inventory_page` 与 `replenishment_preview` 分别得到同一 P001/W01 shortage=55套时，单独验证均通过，合并验证失败并报 `CLAIM_AMBIGUOUS`（先失败 `tests/unit/test_fact_checks.py::test_consistent_inventory_and_preview_observations_share_business_identity`）。
- 修复将库存/补货观测按字段、物料、仓库、供应商/订单、指标和单位建立业务身份；保留来源call_id用于追溯。跨来源同一业务身份使用最新时间判定，同一时点矛盾仍以`CLAIM_AMBIGUOUS`拒绝。
- 反例覆盖：同一时间跨来源55/50冲突仍失败；同一套既有负例继续覆盖不同物料、供应商、字段、单位、旧快照/新值、金额字段与交期范围。
- 定向检查：`uv run pytest tests/unit/test_fact_checks.py -q`，exit 0，12 passed。真实Graph/live追踪尚未重跑，原P03失败仍保留且不重标通过。

## F03：订单工作流Provider写权限

- 红测复现：在隔离Mongo库先启订单工作流，再从同一`local_snapshot`配置批准；旧实现返回completed，说明等待审批后仍通过`MutationService`写订单。该红测在修复前以exit 1失败，订单事实确实发生变更；fixture在finally清理测试库。
- 修复在`MutationService.execute`最终事务入口检查orders/inventory/parts/suppliers四项写能力；`OrderWorkflowService.resume`及持久恢复在approve前使用同一Provider集合检查。失败时不认领resume，审批保持waiting；共享事务入口仍作为第二道检查。Provider未装配时失败关闭。
- 回归：`uv run pytest tests/integration/test_provider_switching.py -q` exit 0，3 passed；组合`test_provider_switching.py test_business_workflow.py test_order_idempotency.py` exit 0，22 passed。snapshot拒绝后orders=2、I001.inbound=10、成功order_create operation=0，run仍waiting_input。local_seed workflow及幂等回归通过。
- remote REST未接通、v1隔离仍开放；本地snapshot门禁不能代表远程ERP验收。

## F06：恢复建议检查全部operation

- 红测复现：`[succeeded, outcome_unknown]`和倒序分别给出`return_committed_result`与`reconcile_external`；failed run也因早期终态分支遮住processing租约。新增反例先以exit 1失败。
- 修复按状态集合统一判优先级：outcome_unknown→reconcile_external，processing→inspect_lease，succeeded→return_committed_result；再处理等待输入与终态。任何路径均不自动重放业务写。
- 定向检查：`uv run pytest tests/unit/test_recovery_matrix.py -q`，exit 0，5 passed。
- 该分类当前仍是TraceService只读建议；尚未接入自动恢复，也没有真实checkpointer存在性查验或完整故障矩阵，因此自动恢复能力保持开放。

## F05：备份恢复namespace和文件集合预检

- 先失败用例：`uv run pytest tests/unit/test_backup_restore_guards.py -q`首次exit 1，3项均失败，旧脚本没有归档dry-run namespace核对、artifact引用核对或storage精确清单。
- format 2 manifest记录来源实际namespace、artifact的`_id/owner_id/run_id/status/storage_key/size_bytes`和全文件sha256/长度。备份前要求ready artifacts与StorageRoot文件集合完全一致；丢失内容、额外文件、reparse point、拼错自定义StorageRoot会失败。恢复先验证manifest文件集合/路径/哈希/长度，再dry-run扫描归档所有namespace；精确符合来源清单后才用`--nsInclude`和`--nsFrom/--nsTo`写入目标。恢复后比较artifact记录，再复制并校验文件。
- 定向测试最终exit 0：`uv run pytest tests/unit/test_backup_restore_guards.py -q` 3 passed；PowerShell Parser对backup/restore脚本均无语法错误。
- 实际隔离演练均在`technologyagent_test_p09_bak_d2b6e2ba`及新target执行。成功恢复后DB核对orders=2、artifacts=1、I001.inbound=10，Storage artifact字节hash一致。篡改manifest来源DB/ns为claim时，恢复在写DB前抛出“Archive namespaces differ... no database write performed”，target collection count=0。三项测试DB已drop，临时storage仍留在忽略目录`.runtime/p09-f05-d2b6e2ba`；清理命令被执行策略拒绝，未继续尝试递归删除。
- 实际演练未验证API授权下载；checkpoint/order/approval全面一致性对照与中途恢复故障矩阵仍需后续补验收，因此F05部分关闭，不作为完整新目录灾备演练通过。

## F04：模型调用追踪和usage完整性

- 红测复现：隔离Mongo持久`model_calls=3`但只有2条model_started时，旧trace给`calls=unknown`或按事件数报2，且仅有一条usage=10的情况下无法区分该值为小计。新增`test_trace_summary_uses_persisted_call_count_and_marks_partial_usage`先因mode=unknown失败。
- 新增`observed_model_stream`统一记录模型调用call_id、actor、purpose、开始/结束、失败和usage状态；接入语义评审、订单抽取及订单正文修订。Graph主调用补purpose及usage_status。事件schema保持向后兼容并重新生成共享schema/前端类型。
- TraceService优先读持久`model_calls`（兼容旧`model_calls_used`字段），否则用事件fallback；mode从run_started可靠取值。summary分开报告真实calls、event_calls/event_completeness、usage_completeness、known_subtotal和missing_calls。只有完整覆盖时才报告总usage。
- 检查：`uv run pytest tests/unit/test_model_observation.py tests/integration/test_trace_summary.py tests/unit/test_semantic_review.py tests/integration/test_order_review_loop.py -q` exit 0，11 passed。覆盖成功、失败、参数脱敏、trace真实持久计数、模式和usage缺失。
- 真实模型全场景调用计数与DB交叉验收尚待F09新批次；此处为fake/集成确定性验证。

## F07：聊天提案恢复与改单金额可审查性

- 红测先复现改单提案接口缺`fact_snapshot`，因此浏览器只看见规范payload/hash，不能核对旧/新单位与金额。修复由服务端读取owner订单、物料单位与报价，保存旧/新明细、数量、单价、行额和总额；list接口返回同一快照与原始run_id。
- 单位白名单红测确认order角色的`order_statistics`、`part_by_supplier`被policy拒绝；P08参考工具注册后只向order角色显露/允许这两项只读能力，analyst仍不可见。
- 原Graph工具环路目前在提案写入后会继续生成最终回答，没有持久原run中断。新增集成用例起初在InterruptPayload拒绝新kind时报错；修复期间又实测发现LangGraph节点只原地改state但没返回`proposal_interrupt`，导致run落入`PLAN_COMPLETE`失败。节点现返回中断字段，Graph持久waiting_input；原run resume要求owner、run、approval、interrupt/version匹配，拒绝payload覆盖，approve前/执行前复核Provider并由服务端MutationService执行。启动恢复支持重复对账同一决定键。
- 集成覆盖Graph产生持久interrupt、Mongo状态、批准/拒绝、同run重放仅一条operation及业务结果。新增浏览器回归改单订单页显示数量/套、单价/行额及原/新总额。新增Mongo/Graph回归覆盖批准、拒绝、提交后崩溃恢复与同键重放；跨页面统一由原run中断记录驱动。订单专家提示已明确只能提案并等待人工批准。订单页改单金额浏览器测试补齐本地会话建立。最终F09门禁结果见下文。

## F08：仍开放的远程与版本隔离门槛

- 远程ERP：远端REST读取/自动分页聚合仍未完整贯穿到统一provider；写入尚无持久remote intent、供应商操作号及超时后同单lookup对账。因此远程写继续关闭，没有调用真实ERP。
- 旧版本：缺少真正不同的v1 builder/schema/namespace ABI隔离和v2发布后旧审批恢复对照；现有P07 v1 fixture只验证既有图升级，不证明P09修改版本仍隔离。此项不通过，不创建阶段标签。
- 该清单是现状交接，未用常量、模拟器或单位测试宣称关闭。

## F09：固定批次与整体验收

- 完整离线门禁：`uv run python -m scripts.verify_stage P09 --mode offline --report .runtime/reports/P09-fix1-offline-final.json`，exit 0、7/7 checks passed；兼容性与专用库seed通过，后端unit/integration **437 passed**，前端typecheck、测试（38 passed）、build和契约检查均通过。全skip伪通过反例纳入manifest门禁。
- 完整browser门禁：`uv run python -m scripts.verify_stage P09 --mode browser --report .runtime/reports/P09-fix1-browser-final.json`，exit 0、2/2 checks passed；Playwright **16/16 passed**，包含订单工作流、P07偏好、P08提案、改单金额、P09桌面1440x900和手机390x844。首轮browser 15/16失败因改单E2E缺少session/me等待，修正测试后新跑全套通过。
- 本轮实际隔离browser库 `technologyagent_test_p09_browser`最终计数：orders=3、approvals=25、operations=12、suppliers=4、inventory_movements=0。F05隔离演练的DB事实/hash见F05；没有连接或写入日常开发库。
- 配置预检仅记录非敏感状态：`MODEL_MODE=live`、模型名和key已配置。第一次启动验收子进程未继承 `RUN_LIVE_MODEL`，该次为 `not_run` 且没有模型请求；随后按显式启用重新执行了固定批次。P03-A06 新批次 `20261026T051124Z` exit 1：9次真实尝试6通过，q1=3/3、q2=0/3、q3=3/3；9次数据库前后均不变。q2三次均给出无效报价 P001/S03。原始全轨迹在 `evidence/P09/live/P03-A06-fix1-20261026T051124Z.json`（SHA-256 `752b9b4e1c82954110ca0f9bd7af07c5b06f1ad6d5ede483856dccea0a3f6772`），历史批次和旧评分未改。
- P09真实模型新批次 `20261026T051120Z-62817dca0c` exit 1：13个外层尝试仅2通过；所有尝试和嵌套轨迹、数据库前后事实保存在 `evidence/P09/live/P09-fix1-20261026T051120Z-62817dca0c/`，完整清单与校验值见 `evidence/P09/live/P09-fix1-live-manifest.json`。F04订单第1、2次通过，第3次业务提交已发生但终态失败：订单数2→3、审批消费及operation各有新增，库存P001/W01 inbound 10→65、on_hand维持20；失败轨迹的评审拒绝 `ORDER_FACTS_MATCH`，run带 `committed_facts=true`。这属于提交后的验收失败，不能记作成功。
- 同批F08 review为0/3；对应P05-A04轨迹显示已提交后 `POST_COMMIT_SETTLEMENT` 因 `TypeError` 失败（`evidence/P09/live/P05-A04-P09-attempts.json`）。F11 specialist为0/3，均以 `REPORT_ARTIFACT_REQUIRED` 失败；订单数2、库存inbound10/on_hand20保持不变。F12偏好与查询为0/3；每次偏好W01都持久化，但查询被 `NUMERIC_MATCH`、`SCOPE_MATCH`、`REQUEST_CONSTRAINTS`、`TARGET_GAP_COVERAGE` 或 `PLAN_COMPLETE` 拒绝，业务订单数保持2。另有完整F11/F12轨迹文件在 `evidence/P09/live/`。以上保留失败原始分类，没有归并成“模型原因”。本批没有调用真实ERP。
- F08仍未关闭：远程ERP分页读取、持久remote intent/外部引用及超时同单对账未实现；真正v1 builder/schema/namespace隔离未验证。F05正式授权下载/完整灾备矩阵、F09要求的其余人工文件打开/新目录一致恢复等本地操作验收也未由本轮覆盖。
- 修复前的完整offline实测exit 1：15 failed/420 passed；定位并修复Graph无可选RunService时评审事件写入异常，以及订单专家缺少提案边界说明；同时把恢复重放夹具改成API真实哈希。最终新批次offline exit 0，完整历史browser首轮15/16（缺session初始化）后修正并重新全跑16/16。失败报告保留为`.runtime/reports/P09-fix1-offline.json`及首次browser报告，最终报告分别为上述`*-final.json`。P09真实批次退出码1，不能以离线/浏览器通过覆盖live失败。
- P07历史未提交改动、`.env.example`、`.dsh-meow/`、`frontend/AGENTS.md`和浏览器生成的未跟踪截图均保留，未加入本轮提交。P09-F07提交`d4d25f71acabfe6711b7b1e07f1b868b1a7b15a8`、F08开放项记录提交`953f80931ef4b9bd0f86a76143a8e9f02b136f27`、offline/browser提交`fd83a04a8c82e1791d97185bb9aac7a3e8aeda44`已推送。该提交的 Actions run `40272542469` success，但唯一 job 为 `p06-offline`，不代表P09专属CI。真实批次证据/状态更新提交将在本次结束前另行核对。
- 因此offline/browser通过，新的真实P03/P09验收未通过，且F08/F05及其他本地运维操作门槛仍开放；不创建`phase-p09`，不开始P10，也不称生产上线。报告中分别保留通过、失败与未运行项。
