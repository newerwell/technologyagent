# P06-fix2：金额字段绑定与P03真实验收 Implementation Plan

> **For agentic workers:** 按 superpowers:executing-plans 逐项执行。产品实现由用户选定的其他Agent完成；本聊天只提供方案及复核。只完成本补修，不开始P07。

**Goal:** 单价、总额、数量和范围按各自事实验证；库存/供应商查询完整回答用户请求；在修复后重新完成固定3×3真实验收。
**Architecture:** 在现有Graph/服务/工具边界内增加共用事实索引与主张核对，订单及只读回答使用同一字段/单位语义。业务计算复用domain与现有查询服务，模型选择工具、组织说明，硬检查决定是否允许发布。
**Tech Stack:** 当前锁定Python/Pydantic/LangGraph/Mongo/Next.js，金额使用整数分与Decimal转换，不新增模型供应商或解析框架。
**Spec:** [共享契约](../specs/CONTRACTS.md)、[P03](../specs/P03-agent-tools.md)、[P05](../specs/P05-harness-review.md)、[P06](../specs/P06-artifacts-sandbox.md)、[P06补修历史](./P06-followup.md)。规划基线`ddd2ab3e8eca8f19d119bda21dd589b30cc241a4`；实施前核对远程最新状态。

## 当前事实与设计选择

- 已确认HTML报告显示正常，已写入evidence；不再要求用户重复查看同一文件。Linux CI已成功，传输、文件授权等已修部分保留回归。
- 新残留：`services/order_workflows.py::_order_answer_fact_check`把unit_price/line_total/total放进同一集合。真实总额66000分、单价1200分时，“总额12元”“单价660元”都通过。
- 最新9条P03真实记录原判3/9，当前gate只读回放6/9；未发起新的真实验收。剩余第1/6次有NUMERIC_MATCH拒绝，第5次没有符合要求的7天预览与完整答案。不能把三条都归为供应商执行异常。
- 推荐共用字段与范围核对。仅增加两个金额正则无法解决跨订单/零件/仓库和表格同值借用；整体更换Agent框架或全量迁移JSON输出超出本次需要。
- 本轮不强制改造ModelPort：保留文本候选，提取业务主张后核对；对核心业务数值采用明确字段的受控渲染。无法确定字段/范围的业务主张返回明确不足并走已有有界修订，不能默认通过。

## Global Constraints

模型20次、工具30次、累计活跃180秒，模型单次至多60秒，普通读工具15秒；最多2次修订/3次评审。已提交订单只读核对，不重放写入。沿用owner/run隔离、持久决定与累计预算。正式token仍在所有硬检查之后发布。

不改固定题目、不删除失败轨迹、不放宽事实检查换取绿灯；旧标签不移动。真实调用只用隔离测试库，密钥不输出或入库。HTML人工确认、离线/浏览器测试、历史轨迹回放与新真实调用分别记录。

## 文件分布与接口

| 文件 | 职责 / 本次动作 |
|---|---|
| `backend/app/agent/fact_checks.py`（新） | 轻量FactKey/FactIndex/BusinessClaim及共用核对，不依赖模型/DB/UI |
| `backend/app/agent/evidence.py` | 从成功工具结果构造具名、具范围的事实；复用共用核对 |
| `backend/app/services/order_workflows.py` | 从持久订单适配事实，每轮检查正文，删除混合数字集合逻辑 |
| `backend/app/agent/graph.py`、`harness.py`、`review.py` | 任务约束、证据覆盖、修订原因及发布边界 |
| `backend/app/contracts/workflow.py` | 仅在诊断/约束确需跨事件持久化时追加兼容字段；先更新共享契约 |
| `scripts/live_acceptance.py`、`tests/live/test_readonly_agent.py` | 独立事实/覆盖/终态验收，不信服务自报通过 |
| `tests/unit/test_fact_checks.py`（新） | 字段、单位、作用域和歧义边界 |
| `tests/integration/test_readonly_scope_answers.py`（新） | 真实工具与Graph、补查和多实体答案 |
| 现有订单/事实/live gate测试 | 增补反例，不复制测试到第三套入口 |

建议内部接口：`build_fact_index(facts) -> FactIndex`、`validate_claims(claims, index) -> ClaimValidation`。FactKey至少含entity_type/entity_id/field及part_id/warehouse_id/supplier_id/order_id；Fact值含value/unit/source_call_id/as_of。内部类型优先dataclass；不为未来功能创建通用规则引擎。订单根`total_cents`映射为`order_total_cents`并绑定order_id；订单行`unit_price_cents/line_total_cents/quantity`绑定order_id+part_id，supplier/warehouse继承所属订单；其他工具结果的同名字段按原实体类型保留，不能混用。

## Task 1：固定失败样例与范围基线

**Files:** 新增`tests/unit/test_fact_checks.py`；扩展`tests/unit/test_order_review_bounds.py`、`test_evidence.py`、`test_live_acceptance.py`。

- [ ] 写红测：持久55件、单价1200分、行额/总额66000分；正确“数量55件、单价12元、总额660元”通过，错误“总额12元”“单价660元”失败。
- [ ] 增加两订单/两零件/两供应商样例：一个实体合法的金额不能借给另一个；多行Markdown第二行也严格按表头核对。
- [ ] 覆盖660元/66000分等价，12.001元、负数、布尔、NaN/Infinity拒绝；数量55、55.0如何等价由整数数量规则统一决定，不用float四舍五入修复错误。
- [ ] 从本地最新批次提取最小脱敏事件/工具结果与被拒原因，保存小型测试fixture；只保留必要合成业务字段，不复制密钥/原始用户数据或整份运行日志。
- [ ] 对失败数字2、36、7、10、12、1、500分别定位：字段/单位/实体、产品描述数字、聚合计数、用户约束或真正错误。候选正文缺失时先记录证据不足，不凭数字猜原因。
- [ ] 运行新增测试确认原实现失败，记录退出码和反例；在此之前不反复调用真实模型。

## Task 2：金额与数量按字段、单位、实体核对

**Files:** 新增`agent/fact_checks.py`；修改`agent/evidence.py`、`services/order_workflows.py`及中文README。

- [ ] 分别保存quantity、unit_price_cents、line_total_cents、order_total_cents。禁止任意字段值集合互相匹配；“单价/行金额/订单总额”必须选对字段。
- [ ] 同一实体不同版本/观察时间保留快照边界，出现冲突时明确选择当前有效快照或报告不足，不把历次查询的所有数字混在一起。
- [ ] 建立订单、订单行、物料、仓库、供应商范围。只有一条可适用事实时可补全省略范围；多条候选不唯一则CLAIM_AMBIGUOUS，要求补明确说明，不任意选第一条。
- [ ] 金额转换使用Decimal，由元精确转整数分，分以下精度不静默round；数量走整数规则。保留符号，不把编号/日期/产品规格直接当金额或数量。
- [ ] `_order_answer_fact_check`仅做持久订单→FactIndex适配，转调共用验证，不能保留原全局cents集合兜底。对原无显式业务数字的说明仍检查订单来源和结果真实性。
- [ ] 每次改写后重新运行硬检查；ORDER_FACTS_MATCH失败不调用语义评分放行，仍最多两次修订。说明失败保留已提交事实。
- [ ] 运行Task1单测，再扩展`test_order_review_loop.py`：先生成交换单价/总额的错误说明，再正确修订；只新增一单，审批消费一次、operation一条、inbound加一次。错误正文不得成为正式最终摘要。
- [ ] 显式提交该任务，更新服务/agent README的字段核对与歧义行为。

## Task 3：P03任务约束与完整数据范围

**Files:** 修改`agent/graph.py`、`harness.py`、`evidence.py`、`review.py`；必要时扩展workflow内部状态；新增`test_readonly_scope_answers.py`。

- [ ] A06按既定fixture/会话范围验证W01；生产请求缺仓库且影响结论时，明确多仓范围或走现有补充信息规则，不能把测试默认值硬编码成所有业务的默认仓库。
- [ ] 将用户请求中的仓库/物料/交期上限作为任务约束保存；它们是request_constraint，不冒充工具观测事实。用户说7天，不要求工具返回某条供应商lead_days=7才允许复述该条件。
- [ ] 针对指定物料/最大交期的推荐，要求有服务端已应用该筛选的证据（现有replenishment_preview能力）。若仅查quote_list/全仓库存，计划仍有未完成约束；进入补查修订，不能通过删掉“7天”把请求改成普通推荐。
- [ ] 业务规则仍由现有服务决定，不能在Graph/提示词重复计算采购金额或硬编码测试答案；按任务语义校验证据，不按固定题目原文或question_index编写产品分支。
- [ ] 库存问题保留多实体范围。按当前fixture的目标库存缺口口径，W01正缺口为P001=55、P003=36、P004=10；安全预警口径是projected<safety_stock，只有P001/P003。两种查询及计数必须区分，不能把“低安全库存”和“低目标库存”默认为同一集合。
- [ ] 明确“哪些零件要补货”采用目标缺口口径并展示每个正缺口；“库存预警”采用既有warning口径。该选择作为本方案的产品口径写入契约；不改stock_state算法。
- [ ] 构造完整事实来源、聚合计数与分页完成依据：统计值由服务端派生并引用完整范围，不让模型凭空报2/3类，也不让合法聚合数因原始记录没有同值而误拒。
- [ ] 核心事实段由已核验字段渲染；自然语言仍可解释限制/建议，出现新的业务主张同样验证。产品名“前轮250mm”等描述绑定目录字段，不按通用数值规则误判。
- [ ] 集成验证三类任务、跨仓库、两个同名零件、空查询、分页、无报价；正确答案通过，漏一条必需记录/错仓库/错供应商/过期报价失败。保留原请求和语义评审输入测试。
- [ ] 提交任务并更新契约及agent模块README。

## Task 4：独立验收与运行证据一致

**Files:** `scripts/live_acceptance.py`、`tests/live/test_readonly_agent.py`、`tests/live/test_harness_review.py`及现有gate单测；必要时只改真正有错的`services/runs.py`事件/快照序列化。

- [ ] 验收器核对数据、工具参数、最终答案覆盖与服务模式，不能直接复用服务的review.passed作为唯一判据。Q1覆盖Task3约定集合；Q2核对P001/W01、7天上限、S01/5天/55件/66000分；Q3明确无有效报价，不能推荐失效S03。
- [ ] 固定题目oracle直接按fixture/DB快照核对预期实体、字段和覆盖集合；可共享安全的事件解析，不能只调用同一个生产事实检查函数就宣布独立验收通过。
- [ ] 用失败事件重放定位“persisted RunView facts differ”到底是哪一字段。failed事件与持久failed一致时不能误报；真实summary/status/review/committed_facts不一致时修收尾事务/序列化，不能去掉断言掩盖。
- [ ] 工具结果验收优先读取完整持久结构；UI用的截断result_summary无法解析时记证据不足，不能当模型选择错工具。保留原call_id、args和as_of。
- [ ] 回归fake服务、无工具、无关正文、全skip、相反结论、错字段、多实体漏答和正确完整答案。P003括号描述的已修用例继续通过。
- [ ] 历史回放只用于定位与回归，原始3/9与当前回放6/9分别保留；不追认成新真实验收。提交任务及测试。

## Task 5：分层回归与固定真实3×3

先运行针对性测试，再完整回归；下列是未来实施命令，不表示本方案已执行它们：

```powershell
$env:MODEL_MODE='fake'
$env:RUN_LIVE_MODEL='0'
$env:MONGODB_DATABASE='technologyagent_test_p06_fix2_offline'
uv run pytest tests/unit/test_fact_checks.py tests/unit/test_evidence.py tests/unit/test_live_acceptance.py tests/unit/test_order_review_bounds.py -q
uv run pytest tests/integration/test_order_review_loop.py tests/integration/test_readonly_scope_answers.py tests/integration/test_stage_manifest.py -q -rs
uv run python -m scripts.verify_stage P06 --mode offline --report .runtime/reports/P06-fix2-offline.json
```

浏览器阶段另起环境，先确认端口及现有服务归属，仅停止本轮启动的服务：

```powershell
$env:MODEL_MODE='fake'
$env:RUN_LIVE_MODEL='0'
$env:MONGODB_DATABASE='technologyagent_test_p06_browser'
./start.ps1
uv run python -m scripts.verify_stage P06 --mode browser --report .runtime/reports/P06-fix2-browser.json
# 完成后仅在确认服务由本轮启动时执行 ./stop.ps1
```

- [ ] Windows有既知TEMP权限问题时使用仓库下唯一pytest basetemp，并记录原因；不调整测试期望来掩盖环境错误。
- [ ] browser前启动fake隔离服务，确认真实下载/跨轮历史和已有审批恢复仍正常；不要把夹具href断言标成真实下载。
- [ ] 离线/集成通过后，启动live隔离服务，在固定fixture下执行原三题各三次，保存一个完整批次9条。按原题运行，不缩窄题目、不只挑成功尝试；请求付费模型时严格使用现有显式opt-in入口。
- [ ] 9/9才关闭P03-A06；失败则保留候选/工具/检查原因与DB前后，说明是真答案错、校验误拒、范围遗漏、执行错误还是证据不足。不得自动无限重跑直到凑齐成功。
- [ ] 订单A04同时核对正确说明修订、相同数字跨字段错误拒绝及只新增一单；fake流程与live修订的边界明确记录。
- [ ] 本地/远程Linux CI分开验证；HTML用户确认保持，不让用户重复完成同一视觉检查。其他尚未完成的正式下载等门槛仍单列。

## Task 6：证据、状态与Git交付

- [ ] 新增`evidence/P06-fix2.md`：逐项测试、命令退出码、真实9次明细/分类、订单事实、Windows/Linux CI、已完成和not_run；原证据不覆盖。
- [ ] 更新STATUS、spec、实施入口和相关中文README，修正P04/P05仍重复旧未修结论的表格，区分原反例关闭与新字段绑定残留。
- [ ] 显式暂存本任务文件，不纳入`.env.example/.dsh-meow/frontend/AGENTS.md`及日志/密钥/运行数据库；每个任务commit，最终push并核对远程SHA及对应CI。
- [ ] 严格前置、P06剩余要求全部关闭前不创建完成标签，旧phase-p05等不移动。补修可以可审查上传，但不能称全部验收通过；不开始P07。

## 完成判据

| 检查 | 必须达到 |
|---|---|
| 金额字段 | 总额12元/单价660元被拒；总额660元/单价12元通过 |
| 实体范围 | 跨订单、物料、仓库、供应商不能借用相同数字 |
| 已提交订单 | 修订/失败/恢复不再增加订单、审批消费、inbound |
| 库存回答 | 按指定口径覆盖完整W01集合，预警与缺口统计区分 |
| 7天推荐 | 有筛选依据，正确回答S01/5天，金额/数量来源匹配 |
| 无有效报价 | 明确限制，不以失效历史价格推荐采购 |
| 验收与证据 | 新批次真实9/9，服务端事件/RunView/DB一致；无skip假通过 |
| 交付 | 相关回归及Windows/Linux CI通过、远程SHA核对，剩余P06门槛单列 |

## 发给实施 Agent 的提示词

```text
你是TechnologyAgent实施Agent，只完成P06-fix2，不开始P07。
目录C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent，远程https://github.com/newerwell/technologyagent.git。
先核对AGENTS、STATUS、远程main与工作区，保留.env.example、.dsh-meow/、frontend/AGENTS.md。
阅读docs/implementation/P06-fix2-implementation.md，按Task1–Task6执行。
先复现总额12元/单价660元误放；实现共用字段/单位/实体核对，每轮订单正文硬检查。
再修P03任务约束与多实体答案，区分目标缺口与安全预警，7天推荐补齐服务端筛选证据。
从现有失败轨迹分类修复，不放宽验收、不缩窄题目、不把历史回放当新真实验收。
相关测试通过后固定三题各三次重新真实验收；保留完整9次及数据库对照，失败如实记录。
HTML报告用户已确认显示正常，不重复要求用户操作。相关正式下载等未验项仍单列。
更新evidence/P06-fix2.md、STATUS及README，逐任务显式commit，push核对远程SHA/CI，旧标签不动。
报告实际通过/失败/not_run与commit，严格验收未关闭不打完成标签，随后停止。
```
