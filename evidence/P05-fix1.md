# P05-fix1 与前置验收补充（2026-10-24）

## 范围与基线

只补修 P05 与已列明的 P03/P04 残留，不开始 P06。基线 `75b18ef421d8c2e36ac6089db696ebe4965504f6`，远程 `origin` 为 `https://github.com/newerwell/technologyagent.git`。原 `phase-p04`、`phase-p05` 标签不移动。提交范围排除既有 `.env.example`、`.dsh-meow/`、`frontend/AGENTS.md`，并排除 `.runtime` 中的实时轨迹、报告和数据库；不读取或提交模型密钥。

## 修复与确定性覆盖

| 计划项 | 实现/覆盖 |
|---|---|
| F01 / P05-R01 | 订单事务提交后的 settlement 异常统一收敛：保留已提交订单、operation、审批和结果事件，不重放副作用。`tests/integration/test_order_settlement_failures.py` 覆盖 RuntimeError、TimeoutError、cancel、deadline、limit。 |
| F02 / P05-R02 | 订单先做确定性硬检查；仅硬检查通过后调用语义评审。最多2次正文修订/3次检查，修订只读已核验订单，不调用写工具。`tests/integration/test_order_review_loop.py` 覆盖首轮漏单号后修订、三轮失败与硬检查失败。 |
| F03 / P05-R03/R04 | 图状态携带并恢复原始请求；计划受当前执行能力约束，读建议与明确下单意图区分；失败步骤可重试，成功证据可完成计划。相关覆盖在 agent tool、plan update 与 resume integration tests。 |
| F04 / P05-R05 | `QueryEvidence` 携带成功查询调用、工具参数、来源、时间和总数；空结果可支持“无数据”结论，不制造实体引用。事件 schema、前端 PlanPanel 与合同文档同步。 |
| F05 / P03-R02/R03/A06、P05-R06 | 数值校验保留负号、按实体字段/单位/范围绑定；正式正文通过评审后发布。live验收核对实际服务模式、工具范围、最终答复和业务库前后快照。历史轨迹保留；本轮 P03 固定3×3结果见下文，不用历史首轮替代。 |
| F06 / P04-R04/R07 | 决定按 run 与幂等键保留请求hash和结果；相同键同请求返回原决定，不同请求冲突。编辑字段在节点与服务间传完整 patch 并重验。覆盖见 `tests/integration/test_workflow_decision_history.py`。 |
| F07 / P04-R02/R09 | 取消使用状态 CAS，按已成功操作生成部分取消事实；活跃耗时持久化、等待人工输入时暂停，恢复后扣减累计预算。覆盖见 checkpoint resume 测试。 |
| F08 | Run终态增加已提交事实/摘要，刷新重放保留状态；聊天页显示提交后评审失败，计划面板展示查询证据。模块 README 与契约文档同步。 |

## 离线与浏览器

- 针对性回归：settlement/review/history/multi-supplier/cancel/budget 测试 **10 passed**；证据解析及 live acceptance 单测 **20 passed**。
- `uv run python -m scripts.verify_stage P05 --mode offline --report .runtime/reports/P05-fix1-offline-final.json`：exit 0，**9/9 checks**，98 unit、142 integration、34 frontend tests；typecheck、production build、contract check 均通过，总计486.60s。
- P05 browser manifest `.runtime/reports/P05-fix1-browser-final.json`：exit 0，**2/2 checks、E2E 8/8**，67.14s；使用隔离 fake 数据库，覆盖刷新恢复与订单编辑/重启/批准。首次未启动服务的尝试失败；修正后因浏览器重启子进程继承 `.env` 的 live/P04 配置而失败，修正环境隔离后复跑通过。失败报告保留在 `.runtime/reports`。

## 真实模型与数据库事实

- P03 固定问题顺序为既有 A06 三题，各运行3次，本轮批次 `20261024T132030Z`，共9次。严格验收 **6/9**：第1题3/3、第2题0/3、第3题3/3。第2题的三次失败原因分别包含有效7天供应商预览/最终答复遗漏、执行流报错与持久视图不一致；原始请求、工具调用、事件、RunView、数据库前后快照和失败原因完整保存在 `.runtime/live/p03-readonly.json`，无 Key 内容。
- `uv run pytest tests/live/test_harness_review.py -q -rs`：真实只读库存 Harness **1 passed**。
- `uv run pytest tests/live/test_order_workflow.py -q -rs`：修正阶段序列断言后真实订单审批/恢复场景 **1 passed**；隔离库从2→3笔订单、成功操作与已消费审批各增加1，P001/W01 inbound10→65、on_hand20保持。旧尝试中一次失败来自过时的phase序列断言，轨迹仍保存在 `.runtime/live/p04-order-workflow-attempts.json`。
- `uv run pytest tests/live/test_order_revision_a04.py -q -rs`：P05-A04 **1 passed**。首次语义遗漏由测试明确注入；随后由配置的 live 模型修订说明并通过语义检查。隔离库订单2→3、成功 order_create operation 8→9、已消费审批8→9；P001/W01 inbound10→65、on_hand保持20。完整事件/评审/DB轨迹在 `.runtime/live/p05-a04-attempts.json`。
- P05 live 组件逐项执行；最终固定 P03 批次6/9，故 live 阶段清单不满足严格验收。没有再次运行聚合 live manifest，避免重复同一组固定 P03 调用；不能把 A04/库存/订单子项通过替换为 P03-A06。历史批次继续保留，未把失败统一归因于模型。

## Git 与交付门槛

离线和浏览器验收通过，live子项结果如上。远程 SHA、提交 SHA 与 CI run 待提交后补录。由于 P03-A06 本轮真实验收为6/9，整体严格验收未关闭：不创建/移动 `phase-p03`、`phase-p04`、`phase-p05`，不创建 fix1 完成标签，不开始 P06。
