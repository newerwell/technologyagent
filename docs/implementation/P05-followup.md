# P05 与前置补修 Implementation Plan

状态：待用户选定的其他 Agent 实施。本聊天只审查和规划。输入基线 `1ddfc7c`；保留现有架构、历史证据及不可变标签。本次只补修，不开始 P06。

目标：订单提交后能安全评审和有限修订；计划可由真实查询完成；评审看得到用户请求；严格区分模型、硬校验与验收失败。依据：[P05独立审查](../reviews/2026-10-24-P05-review.md)、[P05规格](../specs/P05-harness-review.md)、[共享契约](../specs/CONTRACTS.md)。

## 文件归属与执行顺序

保留 `agent/` 的编排/评审、`services/` 的业务协调、`repositories/` 的持久记录、`contracts/` 的外部类型、`frontend/.../workflow/` 的展示边界。不在路由或组件复制业务核验。未来 P06 artifact/sandbox 模块不在本补修创建。

建议按 F01→F02→F03→F04→F05→F06→F07→F08 实施；F09 汇总验收。先写能复现审查反例的测试，确认失败，再修复，每次只跑相关检查；最后全回归。不用增加一个总能返回passed的假评审器来满足反例。

### F01 可靠结算与提交事实（P05-R01）

文件：`services/order_workflows.py`、`services/runs.py`，必要时 `contracts/agent.py`；新增 `tests/integration/test_order_settlement_failures.py`。

- [ ] 将 start/resume/recover 的 settle 纳入统一保护与终态协调，不重复 append 终态；识别 checkpoint、成功 operation、订单及审批。
- [ ] 提交前失败不声称已提交；提交后 provider/timeout/cancel/limit 不能丢订单事实或卡住 thread。terminal outcome 保留订单引用、review错误与未完成项。
- [ ] 注入事务成功后的五类异常，验证新增订单/operation/消费审批各恰好一条，inbound只加一次；run 可读取、事件正确结束，下一请求不被无期限占用。
- [ ] 在结算前、review事件后、finish前重启/重复恢复，数据库与事件仍收敛；不得重进 submit。

### F02 订单有界只读修订（P05-R02）

文件：`services/order_workflows.py`、`agent/review.py`、`agent/harness.py`；测试 `tests/integration/test_order_review_loop.py`。

- [ ] 硬核验先运行，失败不调用语义模型；复用共用评审契约，避免订单单独维护一套不完整规则。
- [ ] 硬核验通过后若语义失败，构建只读的结果说明修订；最多2次修订/3次评审。模型只能读已核验订单快照或受控查询，不暴露写工具。
- [ ] revision_count、phase、plan、review 和预算在事件/快照/恢复中一致；修订失败清楚区分“订单已提交、说明未通过”。
- [ ] A04 必测：首轮要求补充单号→只改说明→第二轮通过；另测始终失败、硬失败、修订中断恢复。每次都核对 order/operation/approval/inbound 没有二次变化。

### F03 原始请求与任务能力（P05-R03/R04）

文件：`agent/state.py`、`graph.py`、`harness.py`、`services/order_workflows.py`、必要的RunView/checkpoint兼容；测试实际 GraphExecutor/订单入口。

- [ ] 定义原始 request 与独立 candidate_answer，前者初始化一次并持久化；每轮评审和恢复都使用原请求，旧记录从可信初始消息兼容回填，缺失时明确不足。
- [ ] 分类区分“查询补货/采购建议”和“确认下单”；计划受当前执行器能力约束，不能要求只读执行器调用审批/写入。
- [ ] 覆盖九种只读工具的合法计划，包含 inventory_warning；别因补货、采购、订单查询等名词误进写流程。
- [ ] 失败工具也传动作名和call_id，计划显示失败；合法重试后可完成，不永久锁住failed状态。
- [ ] 捕获实际 ModelPort 输入，断言首次、修订、恢复都含原问题；审查表中两条计划反例用正确答案可完成，错误工具/无依据仍失败。

### F04 查询级依据和空结果（P05-R05）

文件：`contracts/workflow.py`、`agent/evidence.py`、`harness.py`、事件导出及消费方；更新 `docs/specs/CONTRACTS.md`、模块README。

- [ ] 定义明确的 query evidence 与 entity ref，不制造实体ID；记录成功调用、范围、时间、total。先更新契约再更新两端。
- [ ] 空页/无有效报价可完成对应查询，结果应说信息不存在或不足；不得由空查询支持某零件的数值。
- [ ] 测空页total0、分页空页但total非0、工具错误、参数范围不符、旧快照缺新字段；生成类型和contract_check必须通过。

### F05 数值绑定和真正回答问题（P03-R02/R03，P05-R06）

文件：`agent/evidence.py`、`agent/live_acceptance.py`、`tests/live/test_readonly_agent.py`、`tests/live/test_harness_review.py`、相关unit/integration；保留审查反例。

- [ ] 以实体、字段、单位、作用域核对主张；保留符号，处理Markdown表头/单元格；将交期筛选条件与供应商lead_days、报价unit_price与total分开。不要继续通过缩窄固定题目或只加提示词绕过事实校验。
- [ ] wrong -55/9999 必拒；合法7天约束+5天交期、700分历史单价必能正确核对；不确定解析应要求改写并说明原因，不放行错误也不强行错误绑定。
- [ ] 验收器独立核对最终正文包含每个固定问题要求的答案，成功工具+“已核对”不算回答。服务实际model_mode需为live，核对工具/参数/实体/来源/终态/DB不变。
- [ ] 测fake服务、无工具、空事件、无关正文、错实体、错范围/数值、全skip以及正确完整回答；测试配置live不能替代服务实际live。
- [ ] 修正历史A06归因：3执行KeyError、29校验拒绝、4通过。新增仅供测试/诊断的脱敏候选正文+拒绝check_id，避免发布错误正文给UI；不保存私有思考或密钥。保留原36轨迹，不能删除失败只报最后通过。

### F06 决定历史与编辑一致性（P04-R04/R07）

文件：`repositories/runs.py`、`repositories/indexes.py` 或专用 workflow decision repository、`services/order_workflows.py`、`agent/order_nodes.py`；更新schema迁移/中文README。

- [ ] 按 owner/run/interrupt/idempotency_key 保留每条决定的canonical hash及结果/状态；同键同payload始终返回原决定结果，同键异payload409。保存后续决定不能覆盖旧键，不能只看当前pending。
- [ ] 测 edit→再次approve后重放旧edit、多草稿第一单决定在第二单结束后重放、并发相同/冲突决定；订单数量和版本不变。
- [ ] 明确支持的edit字段。支持warehouse/supplier则前置和节点传完整patch并重新核验报价/版本；不支持则认领前422，保持pending可纠正。测试实际patch输入和持久草稿，不只测schema。

### F07 取消与累计预算（P04-R02/R09）

文件：`services/runs.py`、`order_workflows.py`、`repositories/runs.py`、`agent/budget.py`、订单节点；测试真实Mongo与可控时钟。

- [ ] waiting取消用CAS与resume竞争，同一决定只能一方获胜；取消文本按已提交operation/订单事实生成，保留部分成功，不固定声称未创建。
- [ ] 测两供应商第一单成功→第二张等待取消；另以屏障强制cancel读waiting→resume提交→cancel继续，核对最终事实、状态与事件不矛盾。
- [ ] 持久化累计活跃耗时和模型/工具次数，start/resume/review/recovery共享额度；人工等待暂停计时。恢复或创建新RunBudget不得重新获得180秒。
- [ ] 可控时钟测试跨两次resume和review累计超限、长人工等待不耗限、提交后超限事实保留；避免真实sleep180秒。

### F08 展示和文档一致

文件：`frontend/src/components/workflow/`、`hooks/useChat.ts`、run reducer/详情与相关测试（仅需变更时），以及 STATUS、spec、计划、各模块README。

- [ ] 展示已提交但评审未完成、修订次数、错误/限额与部分完成事实；刷新/事件重放不丢状态，不把phase=result单独当成功。
- [ ] 浏览器检查订单评审失败→补说明通过，review中刷新/重启、多草稿部分成功后取消、空查询和库存预警；保存实际测试数。
- [ ] 更正旧文档把A04首轮通过映射为修订验收、P05未开始/已全部通过等过时说法；历史结果保留并标日期与适用范围。

### F09 总体验收、证据和Git

- [ ] 先跑针对性反例，再运行 `uv run python -m scripts.verify_stage P05 --mode offline --report .runtime/reports/P05-fix1-offline.json`。manifest需包含本补修新增测试，全部退出码0；类型/构建/契约同步。
- [ ] fake隔离服务启动后运行P05 browser；新增场景不以旧8/8替代。只停本次启动的服务，清理唯一临时库，不reset开发库。
- [ ] 真实模型：固定P03三问题各三次，保留完整9次输入、工具、候选/正式答案、独立事实判定和错误分类；同时P05库存与订单A04。订单A04可受控注入首次语义遗漏，但须标明受控故障与真实调用边界，不能全脚本代替live。
- [ ] 无真实调用条件时明确not_run；失败则如实记录，先提交可审查补修但不宣称前置/阶段验收关闭。不更改题目掩盖未过项。
- [ ] 创建 `evidence/P05-fix1.md`，逐项映射R01–R06与前置残留，记录命令、退出码、当前数字、数据库前后、CI和SHA；更新 `docs/delivery/STATUS.md`。旧evidence不删除，新增审查更正链接。
- [ ] 显式暂存本次文件，保留`.env.example/.dsh-meow/frontend/AGENTS.md`，不推密钥/日志/运行数据库；commit、push并核对远程SHA/CI。不得移动phase-p05/phase-p04。仅在对应严格验收关闭后创建phase-p05-fix1等适用新标签；P03未过不补造phase-p03。
- [ ] 停在本补修交付，不开始P06。

## 可复制给实施 Agent

```text
你是TechnologyAgent实施Agent，只完成P05与前置补修，不开始P06。
目录：C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent
远程：https://github.com/newerwell/technologyagent.git
先核对工作区、main和远程；保留.env.example、.dsh-meow/、frontend/AGENTS.md等既有内容。
阅读AGENTS.md、PROJECT_LAYOUT/EXTENSION_GUIDE、CONTRACTS、IMPLEMENTER-HANDBOOK、INTERFACES。
逐项执行docs/implementation/P05-followup.md F01–F09；反例见docs/reviews/2026-10-24-P05-review.md。
重点先保证提交后结算不悬挂，再实现订单只读修订、原始请求传递、可完成计划和严格事实/验收。
同时补决定历史、编辑字段、取消事实与跨恢复累计预算。先失败用例，后修复，最后offline/browser/live分开记录。
保留失败轨迹，不能全归因模型；不把历史首轮通过当A04修订，不用fake冒充live。
结束更新evidence/P05-fix1.md、STATUS和相关模块README，显式commit/push并核对远程与CI。
旧标签不移动，严格验收未关闭不打完成标签。报告已修、实际通过、失败/not_run和commit，然后停止。
```
