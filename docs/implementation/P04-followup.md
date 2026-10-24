# P04 与前置补修 Implementation Plan

> **For agentic workers:** 用户选定的实施 Agent 按 executing-plans 逐项处理，可对独立任务使用 subagent-driven-development。规划者只审查和写交接文档。只完成本补修，不开始 P05。

**Goal:** 修复 P04-R01–R09，关闭 P03-R02/R03/R07 残留，补齐前置真实验收与订单一致性。
**Architecture:** 保留现有 Draft/Approval/Mutation/OrderWorkflow 分层，以事务租约隔离过期执行者、持久恢复决定协调 checkpoint/run/operation；所有页面共用工作流决定入口。模型调用纳入同一 run 预算。
**Tech Stack:** 当前锁定 FastAPI/LangGraph/MongoDB/FastMCP/Next.js/React；不升级依赖，不改成任务队列或新应用框架。
**Spec:** [本轮审查](../reviews/2026-10-24-P04-review.md)、[P04 spec](../specs/P04-orders-approval.md)、[原P04计划](./P04-implementation.md)、[P03补修](./P03-followup.md)、[共享契约](../specs/CONTRACTS.md)。

状态：待实施，输入97e1972。phase-p04已经存在但本轮独立验收未通过；phase-p03尚不存在。不可移动任何旧标签，不把历史live轨迹当本轮结果。

## Global Constraints

- 订单金额来自服务器报价；批准绑定owner/run/action/草稿version/hash；新订单只增inbound，不增on_hand。
- operation按owner/action/key唯一；120秒租约、至多15秒事务；订单、inbound/version、审批消费、operation结果原子提交。
- 同thread单活跃run含waiting_input；取消不撤销已提交事实；不确定结果先同记录核对，不能开新key重下。
- 模型20次、工具30次、单模型60秒、读工具15秒、活跃累计180秒；人工等待不计活跃时间，恢复不能重置已用预算。
- 保留既有 `.env.example` 修改、`.dsh-meow/` 和 `frontend/AGENTS.md`；不 reset 开发库、不输出/提交Key。
- 旧phase-p04=97e1972保持；补修交付用phase-p04-fix1。P03-A06仍须三个固定只读问题各三次，不以订单manifest 2/2替代。

## Review Focus 与文件分工

| 任务 | 主要文件 | 可独立验收的结果 |
|---|---|---|
| F01 | services/mutations.py、repositories/operations.py、reconciliation.py | 过期执行者不能提交、跨集合结果一致 |
| F02 | order_workflows.py、order_nodes.py、chat.py、runs.py、api/runs.py | 等待/执行/已提交三个取消边界正确 |
| F03 | order_workflows.py、runs.py、checkpoint相关仓储 | 认领后及提交后崩溃仍恢复同run/原结果 |
| F04 | 决定请求契约/仓储、order_workflows.py、mutations.py、useChat.ts | 重放收敛、坏输入可重试、首await前提交锁 |
| F05 | api/drafts.py、orders/page.tsx、ChatPage.tsx及历史DTO | 两页面操作一致，不遗留锁死run |
| F06 | order_nodes.py、工作流状态与审批UI | 多供应商逐张确认，无静默漏单 |
| F07 | drafts.py、domain/orders.py、mutations.py | 停用/未知零件不能被批准写入 |
| F08 | order_workflows.py、runs/budget/模型适配 | 幂等认领先于意图模型，调用/时限可追踪 |
| F09 | evidence.py、integrations/model.py、scripts/live_acceptance.py | 关闭P03三项残留与严格验收 |
| F10 | 正式tests/evidence/STATUS/规格/README | 分层证据、真实验收、远程修复交付 |

backend路径均在backend/app/下，前端路径在frontend/src/下。新增持久字段/决定记录先在CONTRACTS/INTERFACES定义，生成schema及消费者同步；旧checkpoint需兼容，不凭新命名空间让旧状态丢失。

### P04-F01：租约归属必须参与提交事务（R01）

**Interfaces:** OperationRepository以lease_owner/租约状态进行条件写，并返回是否匹配；MutationService失败时回滚，不返回伪成功。

- [ ] 先写真实Mongo失败测试：旧认领后暂停→时钟推进121秒→新认领→继续旧事务。断言旧执行者没有订单/inbound/审批写入；新执行者最终恰好一单、operation succeeded、对账一致。
- [ ] 事务开始与结果提交建立租约条件竞争，验证归属/有效期；mark_succeeded必须匹配一条，否则抛错回滚，不能忽略modified_count=0。覆盖租约在读后被新执行者接管。
- [ ] 保留提交响应丢失读回、事务内故障回滚、同key不同payload409；reconcile不自动修饰已经分裂的事实。跑order_idempotency/approval目标回归后提交。

### P04-F02：统一订单取消与事实结果（R02）

**Interfaces:** cancel针对run的实际工作流类型执行，waiting_input可以终结并释放thread；副作用提交后返回真实结果/核对状态。

- [ ] 真Mongo失败用例：等待审批取消→不得再批准；run cancelled、pending清理、thread可再次使用，审批不可执行。
- [ ] 运行中在批准后/提交前暂停并取消，断言不创建订单；另提交已完成再取消，必须保留原订单及真实说明，不单纯覆盖成“没有执行”的cancelled。
- [ ] 订单图接可信取消/预算控制，在认领、节点及提交边界校验；既有ChatTaskManager取消不倒退。取消后同记录核对未知结果，不生成新key。
- [ ] 覆盖多次取消、跨owner404、刷新/重启后取消与普通聊天；补真实父级UI停止状态证据后提交。

### P04-F03：持久决定关闭resume崩溃窗口（R03）

**Interfaces:** 原子认领resume时保存请求键/hash、interrupt/version、决定/payload及恢复进度；checkpoint应用和operation结果可用于判断已完成/待恢复。不能在持久决定前丢弃唯一pending信息。

- [ ] 先写确定性故障测试：①resume认领提交、入图前崩溃；②订单事务提交、图/终态保存前崩溃；③图保存后、run._settle前崩溃。每项实际关闭并重开Mongo saver/服务。
- [ ] 启动恢复读取实际checkpoint与operation，依据已保存决定恢复同thread/run；成功订单返回原ID，未提交可按原决定继续，无法确认时明确对账。无checkpoint的旧P02运行仍可明确失败。
- [ ] 准备/审批节点可重放但不能无限新增草稿或重复消费决定；用稳定run/草稿业务键做幂等准备，保留checkpoint兼容和图版本路由。
- [ ] 断言订单、审批、inbound、operation、run状态和thread锁共同正确，不只判断聊天文字。静止waiting_input重启用例保留，跑checkpoint/故障测试后提交。

### P04-F04：可纠正输入、幂等决定与UI提交锁（R04/R07）

**Interfaces:** 相同owner/run/决定键及相同payload返回原结果或processing；相同键换payload409；无效输入保留有效中断并返回原422/409。

- [ ] 真Mongo失败用例：B首次查operation为空后暂停→A提交→B继续，应回同单，不得403。成功后的相同resume重放回原run/订单，不能RUN_NOT_ACTIVE；并发approve/reject只有一个有效决定。
- [ ] 恢复前校验edit/supplement完整payload、字段类型、数量、仓库/报价、当前version；无效items/仓库可纠正，不把普通业务错误统一500且failed。恢复中才发现变更时重新形成明确等待。
- [ ] 将持久决定幂等与F03认领结合；Mutation遇到consumed竞争前核对相同已知operation。不能先新增无效operation再说幂等成立。
- [ ] useChat.resume首await前认领独立提交状态；成功/失败/切会话后按所属操作释放。组件+实际hook延迟请求中断言卡片按钮锁定，不能仅手工给busy=true。
- [ ] 覆盖同key不同决定、旧interrupt、跨owner、普通错误后修正重试；正式测试通过后提交。

### P04-F05：订单页与聊天共用决定入口（R06）

**Interfaces:** 服务器返回草稿所属run/interrupt/version和可用操作；工作流草稿通过resume决定，独立草稿才走独立入口。UI不得伪造ui_run替代原工作流归属。

- [ ] 真服务+浏览器失败用例：聊天waiting→订单页批准/拒绝/编辑→返回聊天刷新。原run和checkpoint必须同步，thread正确释放或进入新版本等待，已有订单不变成失败。
- [ ] 两页面接统一F03/F04入口；服务端也约束绕开工作流直接patch/resolve/create时的一致性，不仅隐藏按钮。对账结果回写对应运行展示。
- [ ] 编辑产生新版本与新确认，跨页面旧按钮409并可刷新恢复；批准后重载只显示原订单。跑API、hook和跨页面E2E后提交。

### P04-F06：多供应商逐张确认（R05）

**Interfaces:** 工作流状态保留全部草稿、当前游标/剩余项及每张结果；interrupt_id包含稳定草稿标识和版本，不能只依赖version；每张单独批准。

- [ ] 真Mongo用合法缺货库存构造P001/S02与P002/S01两张新草稿（区分seed旧草稿），批准第一张后继续展示第二张，不能completed。
- [ ] 覆盖一张批准一张拒绝、第二张编辑、逐张金额/来源、各自idempotency key与库存版本；同仓多草稿修改共享库存时重新确认受影响快照。
- [ ] 批准首张后重启/重放，第一张不重复下单且第二张仍能处理；全部处理后摘要说明成功与未完成/拒绝项。UI按每条明细编辑数量，不用单个数量意外覆盖全部行。
- [ ] 跑图/事务/审批UI与多草稿E2E后提交。

### P04-F07：有效零件约束贯穿提交（R08）

**Interfaces:** prepare/patch拒绝未知或inactive零件；Mutation事务重读零件状态，准备后停用使旧批准无效，不写订单/inbound。

- [ ] 先写inactive零件具备有效quote和inventory时仍可下单的失败测试；覆盖准备后停用、修改为停用零件、零件删除、正常active。
- [ ] 复用domain业务校验，不能只在前端过滤；失败不创建可执行批准或operation垃圾。若提交前事实变更，保留明确的新确认路径。
- [ ] 跑draft/approval/order_idempotency测试并断言数据库无副作用，提交。

### P04-F08：订单意图进入run预算和幂等（R09）

**Interfaces:** 请求幂等payload包含完整工作流输入；认领先于模型，重放不再次调用；模型耗时/usage未知为null、调用计数/取消使用同一预算。

- [ ] 受控模型+真Mongo失败用例：同请求两次，实际模型只调用一次、同run、持久model_calls=1；第一次成功后模型不可达，重放仍返回原run。
- [ ] 相同request_id改变fake draft数量/仓库或live message，返回409；完整保存已提取意图和当前步骤，恢复不重复付费抽取。
- [ ] 模型请求遵守剩余总时限/次数/取消；提取的零件、仓库和交期类型严格校验，不猜缺字段。跨等待恢复不重置已用预算；留存脱敏真实意图证据。
- [ ] 跑order_workflow_intent、run原子计数/幂等及超时测试后提交。

### P04-F09：关闭P03三项残留与前置A06

- [ ] P03-R02：先写“缺口66000件、金额55元”“总额66000元”等反例；用显式结构化claim/受控摘要保证字段、实体、范围、值与单位一一绑定。不要继续扩大正则邻近窗口。正常55件/660.00元保留通过，错误不能进入正式token。
- [ ] P03-R03：验收器对工具返回缺55而答案“库存充足无需补货”、错供应商、错金额均失败；校验最终结论及成功工具事实，保留预算内纠错全部轨迹，不把只有工具成功当答案正确。
- [ ] P03-R07：MockTransport的length、content_filter、异常终止不能completed；stop/tool_calls/所支持正常完成规则明确，无usage可正常，半JSON不得执行。
- [ ] 分别运行evidence、adapter、live验收器反例及实际图集成；使用已有显式live配置后才执行P03固定3问题×3次，记录全部尝试/DB对照。无配置则not_run，不用P04意图调用替代。
- [ ] 更新P03-fix证据与未闭项；真实A06及原反例通过后才记录P03验收完成，不能回填历史未执行结果。

### P04-F10：回归、证据、标签与停止点

- [ ] 执行P04 offline、Fake模式browser（含服务重启）以及F01–F09新增正式断言，记录真实数量/最终退出码；新增故障窗口与跨页面/多草稿场景必须实际执行。
- [ ] 条件齐备时跑严格P03-A06、P04 live及live订单browser；记录模型/模式、完整脱敏步骤、订单与库存/审批/operation/run对照，未运行分项写not_run。P04 live manifest 2/2是两项检查，不称两次模型。
- [ ] 新建evidence/P04-fix1.md，保留历史evidence；更新模块README、STATUS、spec/plan和实施入口。P03残留未关不能宣称前置通过。
- [ ] 清理本次唯一临时库/进程/无用测试脚本；标准测试库按说明处理，原.env.example改动和无关未跟踪项保留。显式暂存补修路径、commit、push origin/main，核对远程SHA和实际CI。
- [ ] 不移动旧phase-p04。必需条件全部满足后，最终记录提交创建并核对annotated phase-p04-fix1；P03如补齐验收，phase-p03仅指向真实完成记录并如实说明补验收时间，不伪装历史顺序。缺条件可上传可审查实现，但不标MVP完整验收。
- [ ] 交回规划者复核后停止，不自动开始P05。

## 复制给实施 Agent

```text
只完成TechnologyAgent的P04-fix1及P03残留补验收，不开始P05。先确认实际仓库路径、Git状态、origin和phase-p04=97e1972；保留已有.env.example修改/.dsh-meow/frontend/AGENTS.md，不读出或提交密钥。
读AGENTS、docs/reviews/2026-10-24-P04-review.md、docs/implementation/P04-followup.md、P03/P04规格与原计划、CONTRACTS和STATUS。按F01-F10实施，每项先保留确定性失败用例。
重点修复过期租约旧执行者提交、订单取消、resume崩溃窗口、坏输入消耗中断、决定/写请求幂等、订单页与聊天共用恢复、多供应商漏单、停用零件、模型抽取绕过预算；关闭P03数字字段/单位、最终回答验收、length截断三项残留。
跑P04 offline/browser与新增真Mongo/跨页面故障回归；真实模型条件齐备才跑P03固定3问题各3次及P04 live/browser，分项记录全部尝试与DB事实，不用P04的2项manifest替代P03-A06。更新evidence/P04-fix1.md和模块说明，显式commit/push并核对CI/远程SHA。
原phase-p04等标签不动；全部必需验收满足后用新phase-p04-fix1。未满足则上传可审查实现并如实报告未完成，不标MVP通过、不开始P05。交付后停止等待复核。
```
