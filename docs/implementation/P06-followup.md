# P06 与前置补修 Implementation Plan

> **For agentic workers:** 使用 superpowers:executing-plans 逐项实施；可按明确独立职责委派审查。本聊天只做规划/复核，产品代码由用户指定的其他 Agent 编写。只完成本补修，不开始 P07。

**Goal:** 让用户实际获得数据正确、来源可追溯、历史可恢复的图表/报告，并使执行与跨平台交付可验证。
**Architecture:** 现有业务查询提供事实，受控结构化产物服务负责校验/渲染/登记，Docker只承担隔离执行，API按owner/artifact_id访问，UI按会话及run恢复。保留各层边界，不创建新框架或复制采购规则。
**Tech Stack:** 当前锁定FastAPI/LangGraph/MongoDB、Docker SDK、Matplotlib、Next.js/React；只为必要兼容修复调整依赖，并记录原因。
**Spec:** [P06规格](../specs/P06-artifacts-sandbox.md)、[共享契约](../specs/CONTRACTS.md)、[本轮审查R01–R07/V01–V06](../reviews/2026-10-24-P06-review.md)。基线b905f0d。

## Global Constraints

- 每run模型20次、工具30次、累计活跃180秒；模型单次60秒；普通读工具15秒；等待人工输入不计。
- 沙箱任务30秒、512MiB、1CPU、pids64、输出总量20MiB；非root、只读根、禁网、无宿主挂载/socket；失败不回退宿主执行。
- ArtifactReady只在授权、内容校验、原子文件及元数据登记完成后发布；业务数值仍用整数分；模型语义不能覆盖硬失败。
- 保留既有无关文件、开发数据、原始失败证据和历史标签；旧P05问题已关闭部分不能重复重做。

## 文件职责与后续扩展

`sandbox/runner.py`只做容器生命周期与传输；`charts.py/reports.py`负责固定格式；`agent/tools/analysis.py`负责工具适配和授权数据。建议新增`services/analysis_artifacts.py`协调可信事实→ChartSpec/AnalysisResult→校验→register；不把所有逻辑继续塞进graph或UI。数据集描述、产物验证状态及来源字段放`contracts/artifacts.py`，先改共享契约再生成两端类型。

历史查询由`repositories/artifacts.py`实现，经`services/artifacts.py`授权后提供API；UI按run保存产物，不共用当前run事件游标。P07仅在未来扩展工具允许者/专家，不在本补修创建技能或委派运行框架。

## Review Focus

Linux上传与Windows同时可用→F01；格式正确但金额错误→F02；来源只有临时ID/CSV漏转义→F03；工具超时容器仍运行→F04；Docker慢拖垮库存→F05；追问后旧文件丢失→F06；真实验收假通过→F07；订单正文错误/静默修订/恢复历史→F08。

### F01 跨平台上传与CI（P06-R01）

**Files:** 修改`sandbox/runner.py`、`.github/workflows/ci.yml`（确需时）；新增`tests/unit/test_sandbox_transport.py`，保留既有真实Docker集成。
**Interfaces:** 私有传输辅助函数统一完整写入/EOF/关闭，生产execute仍返回SandboxResult；不让调用方识别平台socket细节。

- [ ] 添加会失败的SocketIO-like/Socket-like传输测试，含部分写入、传输中断、关闭和服务端非0；记录当前sendall反例。
- [ ] 适配当前Docker SDK真实返回类型及完整写入语义，不只针对一个平台私有字段；清理HTTP/socket资源。
- [ ] Windows跑`uv run pytest tests/unit/test_sandbox_transport.py tests/integration/test_analysis_execute.py tests/integration/test_sandbox.py tests/integration/test_chart_output.py -q -rs`，不得skip真实Docker。
- [ ] 在干净Linux runner运行同样真实上传/执行/回收和完整manifest。保留CI40105755949失败证据；修复提交对应新CI必须success，不能凭本机绿关闭。
- [ ] 更新sandbox中文README、显式暂存并提交本任务。

### F02 受控产物链及正文核验（P06-R02）

**Files:** 新增`services/analysis_artifacts.py`、`tests/integration/test_analysis_artifact_flow.py`；修改`contracts/artifacts.py`、`agent/tools/analysis.py`、`bootstrap.py`、`sandbox/charts.py/reports.py`和registry说明。
**Interfaces:** 建议服务入口`generate_chart(spec:ChartSpec, ctx)->Artifact`、`generate_report(format, analysis:AnalysisResult, ctx)->Artifact`；工具输入只引用当前授权数据及受控分析参数，服务核对数值/范围后调用固定渲染器。

- [ ] 先复现报价1200/1100分×55件，CSV总额9999却ready/completed的失败用例；同时测失效S03、错仓库、缺必需输出。
- [ ] 将固定三图与四报告接入真实Agent工具路径，注册对应effect/参数。采购事实和金额来自业务服务，模型只选择分析意图；不能让模型直接提供一份未经核对的金额表。
- [ ] 通用analysis_execute继续隔离执行，但输出与“已核验采购报告”区分；业务产物发布前核验内容/来源/请求所需格式，未完成必须明确返回错误或未验证状态，不能自报passed代替核验。
- [ ] 整链脚本模型先查报价，再通过正式工具生成bar与四格式；下载回读断言S01=66000、S02=60500、55件、P001/W01、排除失效报价；硬失败无正式ready事件。
- [ ] line输入实际有序日期，pie保非负/非零，错误类型明确拒绝。测试经过正式registry，不能只调样例脚本。更新契约和README，提交任务。

### F03 可追溯来源与安全报告编码（P06-R06/R07）

**Files:** 修改`agent/tools/analysis.py`、`contracts/artifacts.py`、`services/analysis_artifacts.py`、`sandbox/reports.py`及模块README；测试`tests/unit/test_report_rendering.py`、`tests/integration/test_analysis_artifact_flow.py`。
**Interfaces:** 授权数据描述至少携带dataset_id、run、原call_id/工具、参数范围、as_of、原始source_refs及容器文件映射；临时ID不作为唯一正式来源。来源字段先明确兼容默认值。

- [ ] 先写run结束后来源只剩不可定位ds_uuid、md/html/csv丢source_refs的反例。
- [ ] cache保留可信元信息，正式登记/事件/报告保留原Q01/Q02等来源与时间；需要快照的保存最小必要脱敏数据，不把私有原始数据随意入Git。
- [ ] 四格式稳定显示/保存scope、来源时间、来源引用、明细、结论、建议及缺项，重启后仍可核对；CSV明确元信息布局，单位保持分。
- [ ] 所有字符串单元格统一转义，包括表头和元信息；numeric_columns验证值确为数值，禁止字符串借数值索引绕过。
- [ ] 回读验证唯一来源ID四格式均存在，原正确数值未变化；公式前缀及空白、逗号、换行、中文在所有字段均覆盖。更新README并提交。

### F04 有界执行和主动回收（P06-R03）

**Files:** 修改`sandbox/runner.py`、`ports/sandbox.py`、`agent/graph.py`、`agent/tools/analysis.py`、必要的`agent/budget.py`；新增`tests/integration/test_analysis_lifecycle.py`及可控客户端单测。
**Interfaces:** SandboxPort需要接收可取消/剩余额度上下文或等效任务句柄；取消必须可终止特定容器。不要只cancel to_thread的Future；容器关联真实run及唯一job，不能全局杀所有sandbox标签。

- [ ] 先写Graph15秒/Job30秒冲突和调用端超时容器仍running的失败用例；用可控时钟覆盖大部分逻辑。
- [ ] 按工具effect区分普通读15秒与sandbox30秒，并始终受run剩余预算限制；创建、上传、执行、收集、销毁全链明确期限。
- [ ] 调用取消/超时主动停止该job并等待回收；上传/收集阻塞可中断；登记前检查run仍允许发布，输出限制覆盖实际收集过程。
- [ ] 真实Docker跑正常CSV、合法20秒作业（经Graph）、无限循环到30秒上限、执行中取消、收集失败；只核对本job已销毁、无幽灵ready/重复产物，不用全局容器列表为空判断并发任务。
- [ ] 错误码区分超时/取消/依赖/非0退出/输出限额，失败不报告隔离成功即等同任务成功。提交任务与README。

### F05 可选能力降级（P06-R04）

**Files:** 修改`agent/tools/analysis.py`、`services/readiness.py`、`bootstrap.py`；扩展`tests/unit/test_analysis_registry.py`、Graph整链测试。
**Interfaces:** 基础registry创建不等待无界可选Docker能力；短时限能力探测可缓存，有效期与失败说明清晰。陈旧analysis调用明确SANDBOX_UNAVAILABLE。

- [ ] 先写慢Docker探测导致普通库存TOOL_TIMEOUT、模型0调用的反例。
- [ ] 在独立短时限内探测/使用缓存，失败隐藏分析能力并返回基础工具；正确关闭已创建registry，不能因可选检查泄漏MCP连接。
- [ ] 测缺镜像、守护进程快速失败、静默不响应、运行中断连；普通库存正常完成，分析明确失败且无假链接。提交任务。

### F06 历史产物与真实浏览器下载（P06-R05）

**Files:** 修改`repositories/artifacts.py`、`services/artifacts.py`、`api/artifacts.py`或会话契约、`frontend/src/hooks/useChat.ts`、`lib/event-reducer.ts`、ChatPage/ArtifactCard；新增`tests/e2e/artifact-history.spec.ts`及API授权测试。
**Interfaces:** 提供按owner+thread/run查产物的稳定结构；补服务端归属验证及索引，返回展示元数据而非storage_key；前端分run存储，当前事件seq互不干扰。

- [ ] 先写run1生成→run2追问→刷新后run1卡片丢失的失败断言。
- [ ] 保留跨轮次文件集合，按artifact_id去重，切换会话清理正确，旧事件不能覆盖当前run状态。
- [ ] 实际服务生成至少CSV/PNG，再通过浏览器点击下载、解析文件与加载图片；追问、刷新、重选会话后旧文件仍可下载。不能仅mock href/src就称完整下载通过。
- [ ] 用户B查询列表/下载A仍404，删除/不存在/未ready返回既定错误；不额外设计未经要求的数据保留政策。更新前后端README及契约并提交。

### F07 前置事实与真实验收（V03/V04/V06）

**Files:** 修改`agent/evidence.py`、`scripts/live_acceptance.py`、`scripts/verify_stage.py`、`tests/live/test_harness_review.py`；扩展evidence/live acceptance/manifest单测。
**Interfaces:** 所有live pytest检查采用统一“不得skip”的类型规则；最终答案验收与工具事实独立核对，P05 live入口调用同一严格校验器。

- [ ] 先写当前P05 live函数接受fake/无工具/无关正文、第三题相反结论通过、新live检查全skip通过的失败反例。
- [ ] 接入服务实际模式、完整终态、正确工具参数/实体/答案；第三题必须明确无有效报价。全skip/部分必需skip按清单失败或not_run，不计passed。
- [ ] Markdown表头只从真实header获取，跨多数据行保留字段；supplier_id进入事实范围；正确历史单价700分可核验，错误S02借S01交期拒绝。保留已修负号/首行表头/7天条件回归。
- [ ] 固定P03三题各三次真实调用，题目不缩窄；保留全部结果/错误分类/脱敏候选。最新历史6/9不能标完成，未跑写not_run。本轮历史A04的fake流程+真实修订边界继续明确。
- [ ] 更新evidence及README，显式提交；不能因部分单测绿关闭全部前置验收。

### F08 订单修订事实、静默取消和恢复决定（V01/V02/V05）

**Files:** 修改`services/order_workflows.py`、复用或扩展`agent/review.py/evidence.py`、相关repo接口；扩展`tests/integration/test_order_review_loop.py`、`test_order_settlement_failures.py`、`test_workflow_decision_history.py`。
**Interfaces:** 每轮candidate必须核对持久订单的实体/字段/单位/范围，硬失败不可被语义改写；正文流式消费受min(60秒,run剩余额度)约束，并响应静默期间取消。恢复决定准确写历史结果。

- [ ] 先用55件/66000分真订单，修订错成999件/9999分且语义passed的反例；修复后拒绝错误正文，保存真实已提交事实且不重放。
- [ ] 将每轮硬检查放在candidate变更之后；只读修订不能改订单/审批，正确单号/金额说明能通过；总修订/检查数与模型预算仍有界。
- [ ] 静默stream不产delta时推进可控时钟并cancel，必须按期限退出；收尾释放运行，已提交订单仍恰好一笔。
- [ ] 修正_recover_one的decision key取值；测认领edit→崩溃→重启恢复→后续approve→重放原edit，返回原结果并保留hash冲突保护。
- [ ] 原正常重放、cancel CAS、完整warehouse/supplier patch、累计活跃预算回归保持。更新README并提交。

### F09 总体验收与Git交付

- [ ] 针对性反例先通过，再运行P06完整offline（隔离db_init、标准seed专用库），实际记录unit/integration/frontend数量、Docker构建及契约/类型/构建退出码。
- [ ] 启动fake隔离服务跑P06 browser，覆盖本次新增整链/多轮产物场景；既有9/9不足以替代。只停止本轮服务，清理唯一临时库/文件，不动其他项目容器或开发库。
- [ ] 人工打开三类图和四格式正式产物，核对中文/单位/裁切/来源/数值。遵守当前文件访问限制，遇拒绝按未验收记录，不改用其他通道绕过；解析通过与视觉通过分开写。
- [ ] 真实模型前置固定3×3和订单A04按条件执行；P06自身不额外强制付费模型，不把脚本演示冒充真实模型。
- [ ] 创建`evidence/P06-fix1.md`，逐项映射R01–R07/V01–V06、实测/历史/not_run、Windows/Linux差异、实际CI、DB/容器和产物；同步STATUS、spec、入口、模块README。保留原失败记录。
- [ ] 显式暂存阶段路径，排除`.env.example/.dsh-meow/frontend/AGENTS.md`、密钥/运行文件/DB；commit/push，核对远程SHA和新CI。旧phase-p05等不移动；P06全部要求与前置严格验收未关闭则不创建完成标签，不能只补报告打开就打phase-p06。
- [ ] 报告已修、实际通过/失败/not_run、commit和标签状态，停在本补修，不开始P07。

## 可复制给实施 Agent

```text
你是TechnologyAgent实施Agent，只完成P06及前置补修，不开始P07。
目录C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent，远程https://github.com/newerwell/technologyagent.git。
先核对HEAD/远程和工作区，保留.env.example、.dsh-meow/、frontend/AGENTS.md等既有内容。
读AGENTS、PROJECT_LAYOUT、EXTENSION_GUIDE、CONTRACTS、IMPLEMENTER-HANDBOOK、INTERFACES。
逐项执行docs/implementation/P06-followup.md F01–F09，反例见docs/reviews/2026-10-24-P06-review.md。
先修Linux SocketIO上传与CI，再接真实受控产物生成/事实核验，修时限/回收、普通查询降级、来源和历史文件。
同时补订单正文数值/静默修订/恢复决定，以及P03/P05事实与真实验收门槛；不要重做已关闭问题。
先失败用例再修复，完整offline/browser、实际文件打开、真实调用和Linux CI分开记录。
更新evidence/P06-fix1.md、STATUS和模块README，显式commit/push核对远程与CI，旧标签不移动。
严格验收未关闭不要打完成标签。保留失败证据，报告实际结果后停止。
```
