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
