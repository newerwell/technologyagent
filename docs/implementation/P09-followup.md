# P09 与前置补修 Implementation Plan

> **For agentic workers:** 用户指定的实施 Agent 按 superpowers:executing-plans 逐任务完成。本聊天只审查、维护计划/证据；不据此启动产品修改，不开始P10。

**Goal:** 让最终验收准确反映用户结果，关闭本轮高优先级缺陷，并补齐可诊断、可恢复的本地演示交付。

**Architecture:** 验收从终态、工具成功与独立DB事实判定；事实核验保留业务身份/单位/快照；Provider检查在共享业务写入口贯穿。追踪覆盖全部模型入口，恢复先确认所有operation与checkpoint；备份/恢复有写前namespace与文件完整性预检。沿用现有run/operation/checkpoint，不搭第二套任务系统。

**Tech Stack:** 现有Python/Pydantic/LangGraph/MongoDB/HTTPX/FastMCP/Next.js/Playwright与PowerShell7，保持锁文件版本。

**Spec:** [P09独立审查](../reviews/2026-10-26-P09-review.md)、[P09 Spec](../specs/P09-acceptance-operations.md)、[最终验收矩阵](../specs/FINAL-ACCEPTANCE.md)、[共享契约](../specs/CONTRACTS.md)。审查基线af18b89+既有未提交P07补修，接手必须重核Git，不丢弃原改动。

## 文件分工与顺序

验收判分放tests/live及scripts，不能把通过条件写进产品来凑结果。事实身份放agent/fact_checks和evidence适配；Provider规则在integrations/共享service注入；模型观测可在现有ModelPort调用封装集中实现。备份操作保持独立scripts与operations文档；恢复策略由service统一，不由UI推断是否重试订单。

先F01纠正错误通过，F02修事实误拒，F03封snapshot写，F05恢复namespace可与其他任务独立审查；F04/F06补追踪/恢复，F07回到实际聊天与批准界面，F08明确剩余跨阶段边界，最后F09固定批次验收和Git交付。每任务自带失败反例、针对回归、README及单独提交推送，不等全部完成才记录。

## Global Constraints

- 只在`technologyagent_test_*`隔离库和显式测试storage操作；不reset开发库、不执行真实ERP写、不提交密钥/运行目录。测试产生的临时资源finally清理，清理失败如实记录。
- 所有业务写仍需人工批准、服务端canonical payload/hash/owner/provider/version校验和幂等；已提交事实不回滚、不因正文失败重放。
- model/tool共享预算与最大2次修订保持；不得删事实/范围/单位校验换通过，不删除旧失败轨迹。
- 本地与真实ERP验收分开。F01–F14/F17–F18为本地必需；F15/F16缺环境保持not_run。固定真实场景至少3次，保留全部尝试。
- 既有P07改动、.env.example、.dsh-meow、frontend/AGENTS.md先核对归属；显式暂存本任务文件，不git add .、不reset、不强推，不移动旧标签。

## Review Focus

工具参数出现但最终failed仍标通过→F01；一致跨工具证据误判歧义→F02；只读快照等待审批后仍写入→F03；模型评审/提取漏计且usage小计冒充总量→F04；manifest源库错配写到原namespace→F05；已成功operation遮住另一笔未知写→F06；页面通过冒充聊天闭环/金额不可见→F07；远程和版本缺口被阶段推进覆盖→F08；只跑本阶段或混合工作区冒充远端完成→F09。

### F01 修正F12与live门禁，先恢复证据可信度（R01/R05）

**Files:** `tests/live/test_final_preferences.py`、`test_final_scenarios.py`、`scripts/verify_stage.py`；新增 `tests/unit/test_final_acceptance_oracle.py`，扩展manifest单测和FINAL/evidence。

**Interfaces:** 统一live结果校验接收完整events、期望mode、可信偏好DB前后事实及独立答案事实；显式返回passed/failed/not_run和原因。wrapper无论子进程正常、异常、timeout均保存唯一batch/attempt记录，不靠检查名识别skip。

- [ ] 红测：remember失败、fake启动、tool_started W01后工具失败、终态failed/review=false、提前EOF、偏好未保存/未应用，全部不得passed。完整正确设置→新会话查询→答案与DB正确才通过。
- [ ] 修F12：检查remember与followup各自run_started.mode=live、工具成功、唯一completed终态、review通过、无error、完整stream_end；核对owner偏好持久化、实际成功查询范围和最终答案，不止工具请求参数。保存两段完整脱敏事件与DB快照。
- [ ] 红测子pytest exit0但全skip/空收集/部分必需skip，包装器和外层门禁都不得pass；timeout也必须有记录。避免旧同名attempt被覆盖，started_at应在seed/test之前记录。
- [ ] 保留原F12 9个passed=true记录为历史错误证据，新增纠正摘要：9个query均failed；先改文档实际状态，不伪造新的模型成功。
- [ ] 跑新oracle/manifest单测，更新scripts/live README，显式提交推送；修完产品根因后才在F09运行固定新live批次。

### F02 规范业务事实身份，修一致证据误拒（R02）

**Files:** `agent/fact_checks.py`、`evidence.py`、必要的`verified_answers.py`/review适配；扩展 `tests/unit/test_fact_checks.py`，新增或扩展实际Graph集成。

**Interfaces:** 来源记录身份与业务事实身份分离；逻辑身份包含字段、具体单位、物料、仓库、供应商/报价/订单等必要维度，按来源可比性和观察时间选择当前事实。同一事实可带多个source_refs，真实冲突必须拒绝。

- [ ] 红测：inventory I001/P001/W01 shortage55套与preview P001/W01 shortage55套，单独及合并校验同一完整句都通过；合并不改变正确性。
- [ ] 负测：同值不同物料/仓库/供应商、单价与总额交换、55套与55台、旧快照与新值、同时间矛盾仍拒绝；不能简单删除len>1或按数值去重。
- [ ] 实际Graph脚本模型先inventory_page再preview、给出正确W01完整缺口结果应完成；同样输入换错误字段/范围应失败且不发布错误token。报价多工具观察也加入对应测试。
- [ ] 从原P03轨迹逐条列剩余失败原因，不把重放诊断当新live成功；修target-gap覆盖/计划闭环与该任务直接相关的误拒，保留原安全预警与目标缺口区别。
- [ ] 跑事实unit及Graph/harness定向集成，更新README、提交推送。

### F03 Provider能力覆盖工作流、恢复和fake入口（B01）

**Files:** `integrations/business_provider.py`、`bootstrap.py`、`agent/local_tools.py`、`services/{order_workflows,mutations,business_mutations,inventory}.py` 的共享入口、`api/{drafts,runs}.py`；扩展 `tests/integration/test_provider_switching.py`。

**Interfaces:** 从可信装配/持久操作获取provider及能力，实际业务服务在副作用前检查；API、MCP、聊天、resume共用，不能只补一处路由write=True。等待后配置变化也要重查。

- [ ] 红测四模块snapshot：start P001/W01/7天→waiting后approve，必须拒绝业务写；orders仍2，I001 inbound仍10，无succeeded写operation。不要通过隐藏批准按钮代替服务检查。
- [ ] 红测local_seed准备待审批→切到snapshot或remote→resume，旧批准不能通过本地写；原checkpoint/决定保留可解释状态。适用订单、通用提案和库存动作。
- [ ] fake或脚本聊天选择remote无端点时不可返回seed事实，source明确；部分模块配置与跨模块动作检查一致。remote读取尚未接通可明确拒绝，不静默降级。
- [ ] local_seed原订单批准/恢复/取消/幂等继续通过；业务写仍需人工批准。实际HTTP+Mongo、MCP和Graph各有边界用例，更新README/契约、提交推送。

### F04 统一模型追踪与完整性语义（R04）

**Files:** 现有`ports/model.py`调用适配或新增小型观测封装；`agent/{graph,review}.py`、`services/order_workflows.py`、`contracts/{tracing,events}.py`、`services/tracing.py`、生成契约及tests。

**Interfaces:** 所有真实model.stream入口发稳定call_id/actor/parent_call_id/purpose起止；usage未知有coverage标记或总量unknown，已知小计单独标。计数与实际持久model_calls对齐，事件缺失不伪造0。

- [ ] 红测实际fake调用：图两次+语义一次，总实际3、持久3、trace应3；包括提取/订单正文修订、错误/取消、旧run无事件model_calls=2的回退。
- [ ] 模式从可信run_started或可靠持久字段取；普通completed fake/live不能无理由unknown。工具注册数仍与实际调用数分别统计。
- [ ] 两次调用一项usage=10另一项缺失：总量unknown或明确partial+known_subtotal10+missing1，不把10标完整总量；兼容旧事件不乱补0。
- [ ] owner隔离与敏感参数不返回继续验证；通过真实HTTP trace与事件/调用spy/DB计数交叉核对。更新schema生成文件/README/文档，提交推送。

### F05 恢复写前namespace与文件关联完整性（R03/R07）

**Files:** `scripts/{backup,restore}.ps1`、`docs/operations/BACKUP.md`，新增独立测试脚本或 `tests/integration/test_backup_restore.py`。

**Interfaces:** manifest声明真实DB/集合namespace、storage范围、文件集合/hash及关联检查结果；restore预检archive实际namespace、可信来源/目标、全文件清单和DB artifact引用，成功后再报告restore complete。

- [ ] 红测只读dryRun：src归档+claim manifest必须在写入前拒绝，不能映射回src；显式限定nsInclude和来源映射并检测“筛空归档仍exit0”。测试库外namespace一律拒绝。
- [ ] 正常来源→新目标的实机隔离演练：源库前后hash/记录不变，仅目标获得数据。检查空目标/已有目标、不匹配来源、多namespace归档、错误格式/哈希。
- [ ] DB有ready artifact且StorageRoot不存在/拼错，backup应失败；合法无产物库可明确备份空storage。自定义STORAGE_ROOT必须显式/正确解析，不默默复制默认目录。
- [ ] 实际storage集合与manifest集合完全一致；未列文件、缺文件、替换内容、路径逃逸/重解析点均拒绝。恢复后按正常owner API读取artifact字节/哈希，与元数据和checkpoint关联核对，而非只看文件数量。
- [ ] 文件复制或DB恢复中途失败报告失败/部分状态，不声称一致成功；测试只用显式UUID目标，保留审查所需报告，清理只限本次测试资源。先不触碰日常/生产库。
- [ ] 跑边界与正常演练、更新运维说明和evidence、提交推送。受执行策略阻止的用例标not_run，不能改命令绕过或记通过。

### F06 恢复决策以全部业务事实为准（R06及T02）

**Files:** `services/recovery.py`、`tracing.py`、`bootstrap.py`、`runs.py`/`order_workflows.py`恢复使用方；扩展unit，新增 `tests/integration/test_recovery_matrix.py`。

**Interfaces:** 分类输入包含所有operation状态、租约、checkpoint真实存在与版本，输出保留每项待核对事实；未知写/processing优先，不受Mongo返回顺序影响。分类与执行恢复的职责清晰，禁止任意重放副作用。

- [ ] 红测[succeeded,outcome_unknown]及倒序必须得到同一待对账结论；多个成功/未知/processing/failed组合覆盖，终态run有未决写也要明确显示。
- [ ] 从真实checkpointer取得checkpoint_exists与namespace/version；没有查询不能建议resume。waiting_input保留原决定/检查点，已提交订单只返回事实。
- [ ] 将计划承诺的安全恢复接入启动/明确恢复入口，或继续明确标为只读建议；不把恢复classifier单测通过称为自动恢复完成。
- [ ] 独立故障矩阵：认领后崩溃、commit后丢响应、DB不可用、MCP断线、Docker关闭、等待审批重启、浏览器断线。断言无重复单、无错误补写、无永久thread锁、无宿主执行/数据源回退。
- [ ] 跑确定性与真实本地集成，更新RECOVERY.md/模块README、提交推送。

### F07 关闭剩余聊天业务与金额可见性（B02/B03）

**Files:** `services/approvals.py`、`contracts/mutations.py`、`api/mutations.py`、订单页面；专家policy/YAML与graph_versions/通用持久等待编排；扩展业务workflow、E2E与模型脚本测试。

- [ ] 准备order_update时服务端生成旧/新明细、单位、单价、行额和总额，接口/UI可审查；现有quote hash与执行重查仍生效。仅展示quote_id或hash不够。
- [ ] order_statistics/part_by_supplier按需要进入合法角色只读白名单，发现与执行双向限制；未授权业务写仍拒绝。
- [ ] mutation_prepare产生通用提案后，聊天持久waiting_input；刷新/重启后原run可批准/拒绝并由服务端执行规范payload，owner和run关联按已确定契约校验。独立页面跨run执行已支持，不破坏该合法路径。
- [ ] 脚本模型+真实Mongo验证聊天成功/拒绝/重放，页面浏览器验证金额和批准结果；不让analyst自批或直接执行业务写。更新接口/README/证据、提交推送。

### F08 显式处理远程与版本遗留门槛（原开放项）

**Files:** P08-followup F06/F08/F09列出的Provider/remote_mutations/reconciliation与versions实际入口、相应测试和STATUS。

- [ ] 分别列清remote REST读取、自动多页聚合、持久remote intent/关联号对账、v1 builder/schema/namespace隔离的实现与验收状态；不能统称F01–F09已关闭。
- [ ] 若继续实现，按原任务补HTTP模拟器端到端：写响应丢失→重启→lookup同单、POST一次；真实ERP写仍默认关闭。v1行为对照必须改变v2编排后旧pending approval继续用原实现恢复，不是函数引用自比。
- [ ] 如果本次只交本地受限演示，明确保留未支持能力/未通过最终项；不得创建暗示全P00–P09完成的标签。真实ERP无测试环境保持not_run，不要求用户提交真实凭证来替代本地实现。
- [ ] 对实际完成的每项跑其定向回归并独立提交；未实施项用清楚的open清单交接。

### F09 固定新批次、全链路与Git交付

**Files:** `scripts/run_acceptance.py`、stage manifest、FINAL-ACCEPTANCE、P09 evidence/spec、STATUS/README/架构目录、必要E2E。

- [ ] 先核对并交付既有P07相关hunk的归属，不覆盖或混交用户改动；本轮常规工作区结果和远端提交结果分别记录。
- [ ] fake、RUN_LIVE_MODEL=0，执行完整P09 offline与全历史browser，包含P04进程重启、P07偏好/报告、P08批准执行及本轮诊断/恢复；核对exit/失败/skip与实际DB事实。
- [ ] 产品确定性缺陷修好后，按固定三次运行P03/F04/F08/F11/F12真实场景，保留所有新旧尝试/失败、请求/工具/终态/模型模式/审批/订单/DB前后事实；不挑成功凑3/3。
- [ ] F08失败轮的2次修订与最大2次契约分别核对；若用例明确要求一次就应修正文/评审链并证明，不能无解释放宽断言。F11真正生成所请求报告、字节/事实校验成功后才到审批。
- [ ] 补390×844和1440×900上的实际审批/报告下载，不只输入框宽度；从新目录锁文件安装启动，按F05做隔离备份恢复。已有特定HTML显示确认不重复要求用户操作。
- [ ] 更新矩阵与中文运维/架构/模块说明。当前CI仍跑P06 manifest，增加合适P09门禁或准确声明范围；历史CI success不替代当前browser/live。
- [ ] 显式暂存任务路径、commit、push、核对远端SHA。仅所有本地必需门槛关闭后创建phase-p09；真实ERP状态另列，不移动旧phase标签，不开始P10。

## 发给实施 Agent

```text
你是TechnologyAgent实施Agent，只补修P09与前置遗留，不开始P10。
仓库：C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent
远端：https://github.com/newerwell/technologyagent.git

先读AGENTS.md、PROJECT_LAYOUT/EXTENSION_GUIDE、CONTRACTS、实施手册/INTERFACES、STATUS、P09 spec/FINAL-ACCEPTANCE、docs/reviews/2026-10-26-P09-review.md与docs/implementation/P09-followup.md。
重核git status/log/diff/remote；原P07与.env.example等既有改动必须保留并区分，不reset、不git add .、不混入无关文件。

按F01–F09逐任务先失败复现，再最小修复、针对回归、中文README与证据、独立commit/push。优先：F12实际9个failed误记passed、一致跨工具事实误判歧义、snapshot订单workflow仍可批准写库、restore源namespace错配。再补trace全调用/usage完整性、恢复优先级、聊天提案续接/金额展示与已知remote/v1隔离门槛。

只用technologyagent_test_*及本次测试storage，不reset日常库，不未经指定测试范围调用真实ERP，不开放未验证远程写。保留所有旧失败轨迹与原评分，修好后固定新批次验收，不能通过改passed字段/删检查/挑成功凑通过。
最后报告关闭/部分/未完成、真实退出码/DB事实/新旧批次、Git远端SHA；本地必需门槛全过才打phase-p09。未过保持未完成，不称生产上线，停止。
```
