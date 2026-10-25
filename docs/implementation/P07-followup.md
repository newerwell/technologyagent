# P07 与前置补修 Implementation Plan

> **For agentic workers:** 用户指定的其他Agent按 superpowers:executing-plans 逐项实施。规划者只审查和维护文档。只补修，不开始P08。

**Goal:** 偏好、意图、专家权限和技能真正影响正确的业务路径；前置实体/快照/多仓/单位及独立验收不再误放或误拒。
**Architecture:** 父run建立可信有效约束；router选择分析、订单查询或订单准备，专家共享现有预算/服务；事实核对先确定实体和当前快照，再比较字段值。继续保留审批与版本边界。
**Tech Stack:** 当前Python/LangGraph/MongoDB、Pydantic和Next.js，不更换Agent框架，不升级依赖掩盖业务错误。
**Spec:** [本轮P07审查](../reviews/2026-10-25-P07-review.md)、[P07规格](../specs/P07-specialists-skills-memory.md)、[共享契约](../specs/CONTRACTS.md)。基线307edb4；旧phase-p07/phase-p03不移动。

## 文件归属与执行顺序

`services/preferences.py`负责偏好有效值和显式变更，`graph_versions.py`负责版本/意图路由；结构化请求放contracts；订单提取/准备仍在order_workflows，业务核验仍在domain/services。新增小型`agent/request_intent.py`统一查询/准备/否定与任务特征，避免在三个正则中各自解释用户授权。

`agent/fact_checks.py`修范围/快照/单位；`harness/review/verified_answers`修多仓证据与渲染；不在UI重复采购计算。v1/v2封存限定编排/状态/策略ABI，稳定业务服务继续共享，避免复制整套系统。

建议F01→F02→F03→F04→F05→F06→F07→F08→F09。先写失败反例，运行确认，再修实现与针对回归，逐任务显式提交。只有最终需要时跑全量/浏览器/live，不反复请求供应商试错。

## Global Constraints

父run最多2次委派，不递归；模型20次、工具30次、累计活跃180秒，等待人工暂停；最多2次修订/3次评审。分析无业务写、订单不能自批，提交仍走MutationService。owner/run来自可信上下文。偏好只有显式保存才持久化，本轮要求优先。旧版本待审批run保留原checkpoint和授权语义。

## Review Focus

聊天记住未保存/分析无偏好→F01；显式供应商被旧默认覆盖→F02；空任务/直接ID/多物料/否定/订单查询→F03；取消被吞→F04；报告技能遗漏与版本封存→F05；标点借价/旧快照/错误单位→F06；多仓漏证据/独立oracle误放→F07。

### F01 对话记忆与分析有效偏好（P07-R01）

**Files:** 修改`services/preferences.py`、`bootstrap.py`、`agent/graph_versions.py`、`contracts/delegation.py`、必要的显式偏好工具适配；扩展`tests/integration/test_preferences.py`、新增`tests/integration/test_chat_preferences.py`。
**Interfaces:** 父入口生成有效约束及来源（explicit_request/preference）；DelegationRequest.preferences和子请求约束传真实值。偏好写操作使用服务端白名单/owner和显式确认，不给模型任意存储入口。

- [ ] 红测：HTTP聊天“记住默认仓库W02”后preferences为空；正式保存W02后分析仍读取W01、模型上下文无W02。
- [ ] 实现对话保存/查看/删除入口，校验明确“记住”意图；“本轮W02”不写长期记录，“不要记住”不保存。页面/API与聊天共用PreferenceService。
- [ ] 在分析及订单前合并同owner偏好；明确本轮字段覆盖，工具参数和评审均使用同一有效约束，不能只给模型一段提示。
- [ ] 真Mongo+脚本模型验证保存→服务重启→新会话有效；B用户不继承，查看/修改/删除可用；模型上下文/registry调用/最终范围都匹配。提交并更新README。

### F02 明确覆盖与本轮清除（P07-R02）

**Files:** `contracts/order_workflow.py`、`services/order_workflows.py`、`services/preferences.py`、`agent/request_intent.py`；扩展意图/偏好/订单测试。
**Interfaces:** 区分missing、explicit value、explicit clear，保留来源；自然语言提取支持受校验的supplier_id，不把模型输出当用户授权的唯一依据。

- [ ] 红测：存S01，本轮指定S02且否定S01，最终草稿仍S01；本轮不使用偏好/不限交期仍补回默认。
- [ ] 本轮显式值和否定必须反映到有效请求；不修改长期偏好。S02不满足交期时明确冲突/缺信息，不能悄悄换回S01或放宽7天。
- [ ] 校验供应商存在、active、报价有效性、物料/仓库范围。测试无偏好、合法覆盖、明确清除、不可用供应商、过期报价；断言最终持久order_intent/draft，而非只断言effective字典。
- [ ] UI/API旧请求兼容，契约先更新；提交并更新README。

### F03 意图拆分、直接ID、多物料和只读订单（P07-R03/R04/R05）

**Files:** 新增`agent/request_intent.py`；修改`graph_versions.py`、`order_workflows.py`、专家policy/YAML；扩展router/intent/Graph测试及`test_specialists.py`。
**Interfaces:** 解析结果明确analysis_tasks/order_query/order_prepare及否定范围；直接订单ID从可信目录重新核验，分析证据只作组合任务衔接。订单查询走order的只读Graph，准备走持久工作流。

- [ ] 红测覆盖“准备P001在W01订单，7天内到货”空task、直接ID无分析证据失败、多物料缩为一项、查询已提交订单误准备、“不用/不想/暂时不下单”误委派、order_page有基础能力仍被v2过滤。
- [ ] 只有真实分析子任务才派发，不能产生空DelegationRequest；入口4000字与子任务2000字限制一致处理，超限明确可恢复错误，不静默截断授权范围。
- [ ] 用户直接指定P001时查目录ID/active；不强制先分析，也不把ID当名称。多物料完整覆盖，或在准备草稿前明确补充/确认范围，不能丢项。
- [ ] 查询订单只调用order_page/order_get；否定准备时订单准备服务调用0，查询不创建draft/approval。保持白名单双向执行，分析仍不能order_create。
- [ ] 组合分析→报告→准备仍同run、同版本、原中断恢复；脚本模型验证正确/否定/缺字段/多物料，真实Mongo核对草稿集合及订单0写入，提交任务。

### F04 取消、时限与限额透传（P07-R06）

**Files:** `graph_versions.py`、`order_workflows.py`、`specialists/dispatcher.py`，必要时chat协调；新增`tests/integration/test_specialist_cancellation.py`。

- [ ] 红测：共享budget在订单意图stream中cancel，得到failed/ORDER_SPECIALIST_FAILED。
- [ ] 控制异常保留类型或映射为正确cancelled/limit/deadline结果，普通依赖错误再转专家失败；不能以finish把所有failed都改cancelled掩盖真实错误。
- [ ] 覆盖分析中、订单提取静默/有delta、准备前、等待审批、已提交后的取消；真实副作用按已知事实保留。父子同一budget，第三次委派/递归拒绝，不重新初始化额度。
- [ ] 验证终态事件、RunView、thread释放、无后续模型/工具/业务调用；提交及README。

### F05 技能覆盖、启动校验与版本封存（P07-R07/R08）

**Files:** `skill_loader.py`、`graph_versions.py`、`specialists/policy.py`、`bootstrap.py/readiness.py`、`agent/versions/v1.py`及必要版本模块；扩展技能/升级测试。

- [ ] 红测：独立报告没有procurement-report，库存加报告漏报告技能；普通库存不应加载所有技能。
- [ ] 根据任务特征合并最小技能集，声明与实现来源一致，模型实际上下文与持久manifest的id/version/hash匹配；编辑内容hash变化，未知/缺失技能明确报错。
- [ ] 启动校验专家/YAML/skill引用并在ready呈现不可用；错误配置不开放全部权限，也不等到首个用户任务才给不明错误。
- [ ] 固化v1编排入口、schema、节点、策略和namespace契约；路由真正按持久版本选择。保留来自95740ef的旧fixture并实际恢复，增加“修改v2不改变v1”的对照，不用升级后代码重造所谓旧fixture。
- [ ] 稳定业务服务共用，明确允许修复与版本ABI变更的界限；记录DeepAgents兼容选择和v1退役条件；提交任务。

### F06 事实范围、最新快照和计量单位（V01/V02/V04）

**Files:** `agent/fact_checks.py`、`evidence.py`、`services/analysis_artifacts.py`、必要的typed fact契约；扩展fact/order/artifact测试。

- [ ] 红测：P002/W02/S02冒号/换行借用P001的12元；I001旧55/新50都过；同时间冲突不拒；55套写55台通过、正式报告列名硬编码件。
- [ ] 按句子/段落/表格继承明确实体，冒号和换行不能清空范围后借全局值；语义不明确时报告歧义，不能按数值挑最有利实体。
- [ ] 先确定实体/字段当前快照，再比较值。正规化时间与版本；同一快照冲突拒绝，查询历史任务显式指定历史时间，不作为当前事实兜底。布尔与数值一致处理。
- [ ] 保留具体业务单位，不把套/台/件视为可任意互换；转换仅在有明确业务换算时进行。混合单位报告加单位列，聊天/四报告/图表计量一致。
- [ ] 真Graph回归：错误12元不能成为正式token，正确11元通过；旧值/冲突值拒绝；原单价总额、Decimal精度、多行Markdown、历史报价和CSV来源回归保留。提交任务。

### F07 多仓/分页证据和独立oracle（V03/V05）

**Files:** `harness.py`、`verified_answers.py`、`review.py`、`scripts/live_acceptance.py`、相关scope/plan/gate集成与单测。

- [ ] 红测：两仓均成功但plan只保留第一仓；合法齐备两仓状态被renderer只输出最新仓且hard通过；“无有效报价”后追加相反句仍过。
- [ ] 已done步骤仍接收同任务新增证据，完成判据覆盖全部请求仓库/物料/分页和快照；按调用ID/范围去重，失败重试不遗失已核验页。
- [ ] renderer合并完整范围，不能全局仅选最新一个group；覆盖比较使用(warehouse,part)而非仅part，快照按各自范围处理。无完整来源不补造值。
- [ ] oracle检查整个答案的业务结论与建议，拒绝正确片段后追加错结论/失效供应商推荐；独立核对，不仅信服务review=true或同一生产校验器。
- [ ] 实际Graph/完整工具夹具覆盖两仓同零件、两页、空仓、混合成功/失败及冲突时间；固定3×3和原反例继续有效。提交任务。

### F08 全量、浏览器、真实场景与前置验收

- [ ] 先跑新增针对测试，再执行P07完整offline，当前基线167 unit/168 integration/38 frontend仅作历史参考，记录新数量/退出码/skip，不能复制。
- [ ] fake专用`technologyagent_test_p07_browser`启动服务，P07 browser覆盖聊天记住→重启→新会话应用、本轮覆盖、独立报告技能、订单查询/多物料/否定及同run审批恢复；只停本轮服务。
- [ ] P06正式后端授权下载字节和其他报告格式打开仍按原未验项补齐，用户已确认的HTML不重复要求。API字节校验与浏览器真实下载分开记录。
- [ ] 离线通过后真实P07组合场景：专家分析/正式报告/同run草稿/审批中断，核对实际P001/W01/55套/7天/S01/Q01/66000分及DB无订单变化；不以仅有artifact_ready或items非空作为全部验收。
- [ ] 新P03固定三题各三次保留完整批次和数据库前后，9/9才关闭重开的事实/范围验收；旧P06-fix2的9/9保留历史，不反复调用模型凑成功。P07未批准不能宣称live提交已验；如补live批准必须在隔离库明确记录该动作和唯一副作用。
- [ ] Windows/Linux CI分别跑P07适用manifest和必要Docker前置，避免只复用P06job名宣称P07独立兼容性已验。

### F09 文档、证据与Git

- [ ] 创建`evidence/P07-fix1.md`，映射R01–R08/V01–V05，记录失败→修复→实际检查、来源/模式/DB/副作用/CLI及CI；历史失败不删除。
- [ ] 更新STATUS阶段表和README/AGENT-PROMPTS，消除“P07已通过”与“P07未开始”并存；区分阶段交付标签、原反例关闭与本轮独立验收。
- [ ] 显式暂存本任务文件，排除`.env.example/.dsh-meow/frontend/AGENTS.md`、密钥/运行日志/DB；逐任务commit，最终push核对远程SHA与CI。
- [ ] 不移动phase-p07→307edb4、phase-p03→7f69ff1等旧标签；修复全部验收满足才创建适用新fix标签，否则可审查上传但不得标完成。不开始P08。

## 可复制给实施 Agent

```text
你是TechnologyAgent实施Agent，只做P07及前置补修，不开始P08。
目录C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent，远程https://github.com/newerwell/technologyagent.git。
先核对HEAD/远程/AGENTS，保留.env.example、.dsh-meow/、frontend/AGENTS.md等既有内容。
读docs/reviews/2026-10-25-P07-review.md和docs/implementation/P07-followup.md，按F01–F09执行。
先修聊天偏好/本轮覆盖、纯订单和多物料/否定/订单查询/取消，再补技能和版本契约。
同时修前置事实的冒号范围、最新快照、具体单位、多仓证据和独立oracle。
先失败反例后实现，保留审批/owner/run与共享预算，不重做已关问题，不放宽验收。
最后offline/browser/live、真实文件下载和CI分开记录，更新evidence/P07-fix1.md、STATUS和README。
逐任务显式commit，push核对SHA/CI；旧标签不移动，严格验收未关闭不打完成标签。
用户已确认的HTML展示结果保留。报告实际通过/失败/not_run后停止。
```

## 本轮实施与验收状态（2026-10-25）

- F01–F07实现及确定性回归已执行；R01–R08/V01–V05映射、首次失败报告与修复后检查见[evidence/P07-fix1.md](../../evidence/P07-fix1.md)。
- F08：Windows offline 9/9、fake browser 2/2（E2E 11/11）、正式下载API字节/来源核验5/5通过。browser首轮未启动服务的失败报告保留。P03新固定3×3与P07真实专家live为`not_run`，严格live门槛未通过。
- F09：证据、STATUS和模块说明已更新；push/CI结果提交后补录。旧标签不动，不创建完成标签，不开始P08。
