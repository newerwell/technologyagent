# 阶段交付状态

更新时间：2026-10-27（P09-fix3：N01–N04 已修；离线、browser及F06/F09/F13/F17/F18本地门槛通过；live批次仍有P03、F04、F12失败，不创建`phase-p09`）。最新证据：[P09-fix3](../../evidence/P09-fix3.md)。

## P09-fix3 当前状态（2026-10-27）

- N01–N04 已有确定性失败反例与回归：报告查询范围排他核验、库存/预警/报价页集完整性、稳定snapshot ID与可变as_of、供应商否定/转折识别；正式报告必须在文件登记后回读正文并验证范围/来源，才发`report_verified`。
- 完整离线门禁 exit 0，7/7；后端unit/integration 479 passed，前端38项、typecheck/build、compatibility及contract check通过。fake服务下完整P09 browser exit 0，Playwright 16/16。一次live服务未切换的browser失败报告保留，随后以显式fake配置完整通过。
- 新 live 批次`20261027T093027Z-aa523b4add`：13个外层记录10 passed、3 failed。P03-A06为8/9（W01 3/3、7天推荐3/3、P003 2/3；失败轮模型调用正常结束但语义/报价证据评审未通过）；F04为2/3（失败发生在订单提交后说明评审，数据库仍只增加1单/1 operation，inbound 10→65、on_hand 20）；F08严格核验3/3；F11 3/3；F12 2/3。每次尝试与历史失败均保留在`.runtime/live/p09/attempts/`及`.runtime/live/p03-readonly.json`。
- P03历史0/9批次中的7次`MODEL_TIMEOUT`、一次`MODEL_UNAVAILABLE/ConnectError`及一次`RemoteProtocolError`仍按传输失败保留，不解释成业务事实错误。新批次唯一P03失败为`REVIEW_FAILED/SEMANTIC_COMPLETE`，不是传输错误。新F04未复现“持久决定前依赖失败”；本批唯一失败为已提交订单后的评审失败。
- F06旧v1 checkpoint恢复与v2新run隔离回归、F09三图四格式打开/回读、F13 23只读工具与业务库前后核对、F17桌面/手机16/16及F18新检出/安装/启动/备份恢复已通过。F15/F16真实ERP仍`not_run`。
- 代码提交`a9047b3c8cc09022c84f5da521d3a58cfdbfd40d`已推送，`origin/main`相同。CI Actions run `40482819592`成功，job为`p06-offline`；不能代替P09 live验收。新检出在该代码SHA执行安装、启动与独立test namespace恢复验证。
- 最终矩阵未全过：P03-A06、F04和F12 live未达3/3；不创建`phase-p09`，旧标签不移动，不开始P10。

## P09-fix2 当前状态（2026-10-27）

- R01–R05 确定性缺陷关闭：正式报告校验完整分页数据、显式格式及正文/来源/范围/哈希，传播取消/期限/预算异常，并按具体供应商与动作解释否定和转折。
- 提交后订单文字修订契约为最多 2 次修订/3 次检查；每轮只依据已提交事实修改文字，不重放订单写入。修订成功与耗尽回归均确认单一 `order_create` operation。
- 离线门禁 exit 0（7/7）：unit/integration 468 passed；前端 38 passed、typecheck/build、contract check 全通过。浏览器 exit 0，Playwright 16/16。
- 新 live 批次 `20261027T080230Z-c7c0fe00bb`：外层 11/13；P03 固定问题 0/9，F04 2/3，F08/F11/F12 各 3/3。完整失败保存在 `.runtime/live`，没有覆盖历史失败。F02/F03 与 F04 live 门槛仍未通过。
- F06、F09、F13、F17、F18 仍未达到 FINAL-ACCEPTANCE 全通过条件；F15/F16 真实 ERP `not_run`。不标 P09 完成、不创建标签、不开始 P10。

更新时间：2026-10-26（P09独立复核未通过，F12旧通过结论撤销）。当前实施入口：[P09-followup](../implementation/P09-followup.md)，依据：[独立审查](../reviews/2026-10-26-P09-review.md)。原始轨迹与旧评分保留；下方历史结论不覆盖本节纠正，不创建phase-p09、不开始P10。


## P09 独立复核纠正（当前）

- F12原9组真实query全部failed/review=false/FACT_CHECK_FAILED，却被测试记passed=true；完整偏好live通过结论撤销。只出现W01请求参数不足以验收，原轨迹不改。
- 本轮高优先级：一致库存/preview事实误拒、snapshot工作流仍可批准写本地、restore源namespace错配可能越过显式目标；新增trace漏模型调用/usage完整性、live skip防护、恢复优先级及备份完整性待补。
- P08旧13组回查：7关闭、4部分、2开放。变价阻断与本地规范化等改善保留；不能把REST直写修复扩展为所有workflow/fake入口已关闭。
- 主审真实HTTP/Mongo探针仅使用独立UUID库并清理；本轮不请求真实模型或ERP，不执行真实恢复，不代交用户已有P07代码。本轮补修后完整offline exit0、7/7，437后端unit/integration与38前端测试；完整browser exit0、2/2，Playwright 16/16通过。本轮browser测试使用专用technologyagent_test_p09_browser库，应用已停止。

## P09-fix1 实施进度（2026-10-26）

- F01已实现并通过新增定向确定性测试：F12旧9/9“passed”现按原事件重新判定为9/9失败；live oracle要求两段run完整终态、成功工具/偏好/最终回答及DB事实。包装器拒绝空收集/全skip/部分skip，timeout与异常会保存唯一attempt轨迹。
- F02已关闭确定性误拒：inventory_page与replenishment_preview的一致P001/W01/55套事实按共同业务身份聚合；冲突、不同实体/单位/字段和过期快照仍拒绝，定向12项通过。Graph/live尚未重新验收。
- F03已关闭本地snapshot订单工作流批准写入：approve和恢复入口及共享事务入口均核Provider写能力；隔离库回归确认orders仍2、I001 inbound仍10、成功订单操作0、审批run保留waiting。相关Provider/workflow/幂等22项通过。
- F06已关闭分类顺序误判：unknown/processing不再被另一成功operation或run终态遮盖，恢复建议仍禁止自动重放。5项单测通过；真实checkpoint接入和故障矩阵未完成。
- F05写前namespace及artifact文件关联检查已实现并做真实隔离演练：正常target订单2/artifact1/I001 inbound10、文件hash一致；错namespace在DB写前拒绝、target 0 collections。隔离库已清理；本机忽略目录仍保留一次测试storage证据，未递归删除。API授权下载和完整灾备矩阵仍未通过，按部分关闭记录。
- F04已关闭追踪语义缺陷：Graph/semantic review/order extraction/order revision统一有调用起止、purpose与usage状态；trace以持久调用数计数，partial usage只列小计和缺失调用。11项定向集成/单测通过；真实模型计数交叉核验待新live批次。
- F07本地闭环已通过确定性后端与browser回归：改单金额服务端快照、订单角色只读工具、原聊天run持久提案中断、批准/拒绝/恢复/重放和同一事实UI展示均覆盖。
- F08未关闭：远程ERP REST分页和持久写intent/对账尚缺，旧v1 builder/schema/namespace隔离尚未完成；远程写仍关闭，未请求真实ERP。
- F09：最终offline 7/7（437后端、38前端）与browser 2/2（Playwright 16/16）通过。第一次live子进程未继承显式启用变量而`not_run`、无请求；随后显式启用后真实批次实际运行。P03固定3题×3次 exit 1，9次6通过（q1=3/3、q2=0/3、q3=3/3），数据库前后9/9不变。P09 live exit 1，13个外层尝试仅2通过；F04第三次已提交但终态评审失败（订单2→3、inbound10→65、on_hand20不变），F08 review 0/3、F11 specialist 0/3（`REPORT_ARTIFACT_REQUIRED`）、F12 0/3（结构化事实/计划检查拒绝）。全部轨迹及DB快照见[evidence/P09-fix1.md](../../evidence/P09-fix1.md)及`evidence/P09/live/`。未请求真实ERP。F08远程intent/对账及v1隔离仍开放，F05正式授权下载/完整灾备矩阵和其余P09本地操作验收未齐，因此无phase-p09、不开始P10。browser测试库最终orders=3/approvals=25/operations=12/suppliers=4/inventory_movements=0。

## P09 实施交付时综合验收（历史）

- P09 offline exit0，7项门禁通过：409 unit/integration、38 frontend、typecheck/build/contracts/compatibility通过。Fake/browser入口exit0，完整E2E 15/15；桌面1440×900与手机390×844截图已实际打开核对。
- Trace摘要、模型调用事件、恢复分类、run owner隔离、测试库备份/恢复脚本与操作文档已实现。隔离Mongo恢复源/目标run45、order3、approval12、artifact1、event693、checkpoint21、checkpoint write105相等，storage 11文件SHA一致。
- Live使用真实模型但未通过硬门槛：P03-A06固定3题×3次为3/9；F04修正隔离条件后1/3；F08为2/3；F11为0/3；F12原判三轮通过已撤销（9组query实际failed，旧测试误判）。全部成功与失败轨迹保存在[evidence/P09.md](../../evidence/P09.md)及`evidence/P09/live/`。不能标P09完成。
- F09逐项人工打开所有图表/报告、F13逐项23工具独立事实汇总、F18新目录安装启动仍部分/not_run。F15/F16真实ERP为not_run（无环境/授权）。未创建`phase-p09`，无生产上线声明。
- 开始时`main`与`origin/main`为`4abb34c8a5c66fca7e30ac88af2463aef2515d23`。P09实现/证据提交`25cc35d55193cb99aff021ee41b85323ff892e10`已推送并核对远程SHA；Actions run [40263366879](https://github.com/newerwell/technologyagent/actions/runs/40263366879) success，但其job仅为`p06-offline`，不是P09专属门禁。既有P07修改、`.env.example`、`.dsh-meow/`和`frontend/AGENTS.md`保持未提交。

## P08-fix1既有独立复核

## P08 本轮独立复核（当前）

- 审查基线c2427e0；本轮代码/测试验收提交为`519b048ee39b511c74b44d6120924a96ff9a06fc`，其GitHub Actions run [40256439654](https://github.com/newerwell/technologyagent/actions/runs/40256439654) success。证据/状态提交`c252b38`的run [40257289616](https://github.com/newerwell/technologyagent/actions/runs/40257289616) success；现有CI只运行`p06-offline`，不是P08专属门禁。P07报告门槛已单独提交，其余既有P07工作区改动未打包。
- 最终HEAD offline exit0、9/9：212 unit、193 integration、38 frontend；compatibility/typecheck/build/contract通过。完整fake历史浏览器13/13，包含P04订单恢复、P07偏好、P08批准执行与拒绝。
- F02/F03本地闭环/F04/F05/F07及列出的本地残留回归已关闭。F01远程REST真实读取贯穿、F06自动多页聚合部分未关闭；F08持久remote intent/对账、F09持久graph_version隔离恢复未实现。详细实现状态和修复前反例见[evidence/P08-fix1.md](../../evidence/P08-fix1.md)。
- 真实模型固定批次与真实ERP均`not_run`；没有请求真实ERP或开放远程写。remote模拟器不替代真实ERP。原`phase-p08`保持在`c2427e0`，不创建新阶段完成标签。
- 保留P08首次复验在旧browser测试库上的12/13失败轨迹；之后只重置隔离`technologyagent_test_p08_browser`并完整重跑13/13。应用进程已停止，Mongo容器保留；开发库未reset。

## P07-fix1补修与本地验收

- 按F01–F07修复偏好保存/本轮覆盖、订单意图分类/只读查询/多物料/取消、技能组合、版本路由及事实范围/快照/单位/多仓/oracle；新增反例先在修复前失败，具体映射见证据文件。
- Windows P07 offline exit0、9/9，191 unit、169 integration、38 frontend；compatibility、typecheck、build、contract均通过，387.80秒。原P07 browser首次因未启动服务失败，保留报告；按fake与隔离`technologyagent_test_p07_browser`启动服务后重跑，exit0、2/2、Playwright 11/11。
- 报告下载与授权API/事实/范围回读单独运行：5 passed。E2E artifact卡片不视作下载字节验收；用户已确认HTML正常，本轮未要求重复人工核对。
- P03 live与P07 live preflight均为`not_run`：`RUN_LIVE_MODEL=1`与隔离live配置不齐，不发真实模型请求。P03固定三题各三次未执行，不能以历史P06 9/9或P07两项manifest替代；P07真实委派/待审批也未验。
- 本轮未批准或提交订单；只重置专用P07 verify/browser测试库，未reset开发库。既有`.env.example`、`.dsh-meow/`、`frontend/AGENTS.md`保持未暂存/未纳入本轮提交。
- 原phase-p07与phase-p03及其他旧标签均不移动；live/P03严格门槛未关闭，不创建补修完成标签，不开始P08。远程main已核对；GitHub Actions [run 40180805788](https://github.com/newerwell/technologyagent/actions/runs/40180805788) 的`p06-offline` job success（现有workflow无独立P07 job）。证据与失败报告路径见[evidence/P07-fix1.md](../../evidence/P07-fix1.md)。

## P07 本轮复核与历史证据

- 基线307edb4：本轮Windows offline exit0、9/9、426.81秒，167 unit、168 integration、38 frontend及compatibility/typecheck/build/contracts；fake Chromium exit0、manifest2/2、10/10、30.95秒。
- 额外真实HTTP/隔离Mongo探针复现聊天“记住”未保存及分析未应用已存W02；实际router/Graph和纯函数探针发现空分析任务、直接ID/多物料范围、否定/查询错路由、v2订单查询能力、取消/技能/版本契约问题，以及冒号借价、旧快照、多仓证据/单位/oracle残留。
- 审批原链与旧v1恢复回归通过；本轮未发现分析专家可自批或绕过MutationService写入。历史P06-fix2新真实3×3为9/9，原金额交换等反例已修；新边界仍须补修，不能凭历史9/9宣布所有事实核验无缺口。
- 本轮未请求真实模型/ERP；七次历史P07轨迹前五失败、后两同run待审批，未live批准/提交。实际CI40173876207 success，但workflow跑的是P06 manifest的全测试目录；本轮P07完整manifest另在本地实测。
- 本轮应用已停、唯一Mongo探针库已清理，标准test seed/browser库按manifest重置保留，开发库未reset；既有.env.example/.dsh-meow/frontend/AGENTS.md保留。
- 原phase-p07→307edb4、phase-p03→7f69ff1、phase-p04/05不移动；phase-p06不存在。补修严格通过后用新的fix标签，当前不开始P08。

## P06-fix2交付时状态（历史，2026-10-25）

Windows offline 9/9、browser 2/2（Playwright 9/9）、P03固定真实3×3 9/9；新live批次每次数据库前后快照相等，历史失败批次与分类保留于[P06-fix2 evidence](../../evidence/P06-fix2.md)。Linux Actions run [40165201596](https://github.com/newerwell/technologyagent/actions/runs/40165201596)的`p06-offline` job success，代码远程SHA `7f69ff12a1a3d33d80b8e9a798c5bef65aa32de3`。用户已确认指定HTML显示正常，本轮未重复要求检查。P03严格验收已满足并单独交付`phase-p03`；P06正式后端浏览器授权下载和其他报告格式人工打开仍未验，因此当时不创建P06完成标签、不开始P07。实现与逐任务结果见[P06-fix2计划](../implementation/P06-fix2-implementation.md)及[审查](../reviews/2026-10-24-P06-review.md)。旧阶段标签不移动。

2026-10-25人工确认：用户打开`evidence/p06-artifacts/quote-comparison.html`后反馈“显示正常”。范围仅为这份本地HTML的展示；未据此宣称其他格式人工打开或真实后端浏览器下载通过。补充检查49项通过；最新9条历史轨迹用当前gate回放6/9，原始判定3/9保留，尚未重新真实验收。订单金额字段绑定仍需修：持久总额660元/单价12元时，检查器也接受“总额12元”或“单价660元”；不能以数字存在代替字段一致。

本轮基线b905f0d：Windows offline exit0、9/9、506.64秒（115 unit、149 integration、37 frontend及Docker构建/类型/构建/契约）；fake Chromium exit0、manifest2/2、E2E9/9、27.55秒。本轮无供应商/ERP调用，额外真Mongo/真Docker与内存探针边界见审查。应用已停、唯一探针库清理，既有文件保留。远程[CI40105755949](https://github.com/newerwell/technologyagent/actions/runs/40105755949)失败：Linux SocketIO上传错误，5 failed/144 passed；不能被本机通过替代。

| 阶段 | 实施状态 | 验证状态 | 远程交付 |
|---|---|---|---|
| 初始工程规划 | 规格、布局、扩展、Git规则已编写 | 文档检查通过 | 已推送main：8453859614cf00def940e7ba6f0ac90845d937d4 |
| 其他Agent详细实施计划 | 手册、接口、10阶段任务计划与启动提示词已编写 | 文档覆盖/衔接/链接检查通过 | 已推送main：823a8e3（以远程为准） |
| P00 | 已完成 T01–T05：可运行 FastAPI/Next.js、Mongo replica set 事务、配置与本地会话、启停与验证入口；F01/F02 补修已交付 | offline_verified + browser_verified + ci_verified + fix1_offline_verified + fix1_ci_verified；31 integration + 2 frontend tests；真实 Next→Uvicorn 链；Chrome 截图 | 已推送 main：ce66bfb（实现）、1d1acb9（CI 修复）、59d98e3（fix1）；phase-p00=419ab23 不变；fix1 CI run 39959955218 success；phase-p00-fix1 指向最终记录提交，SHA 以远程为准 |
| P01 | T01–T06初始实现已交付 | 历史问题已由 P01-fix1 修复并在 2026-10-24 复核关闭 | 实现5699197；CI run39966870327 success；phase-p01=2328263 已核对，不移动 |
| P01-fix1 | F01–F05已实现：默认seed只补缺失、inbound对账、精确预警、显式旧基线修复、预览代次、会话刷新恢复 | offline_verified + browser_verified + ci_verified + review_closed；2026-10-24 全量回归含本阶段；原 25 unit + 59 integration + 12 frontend；修复前失败用例已保留 | 已推送 main：858916d；CI run 39980552764 success；phase-p01-fix1=449d4c8→9d6faf9 已核对 |
| P02 | T01–T06及原并发补修已实施 | 原R01–R06本轮均关闭；连续运行Chrome回归通过 | phase-p02=d8415ce、phase-p02-fix1=d493ca5已核对，不移动 |
| P02-fix1 | 已交付，连续运行补修由P03-fix1补齐 | 本轮全量回归与Chrome旧刷新窗口通过，原问题关闭 | 7267378 / phase-p02-fix1→d493ca5，不移动 |
| P03 | 原金额字段/Markdown/供应商/历史单价等反例已补修；固定P06-fix2批次确有9/9 | 本轮新增冒号/换行跨实体借价、旧快照、具体单位、多仓与独立oracle残留，独立通用事实验收重开；本轮无新供应商请求 | phase-p03→7f69ff1不动，历史9/9保留；当前V01–V05见P07审查 |
| P04 | P04-fix1租约、checkpoint、跨页恢复、取消、决定历史和预算补修已记录 | P04-fix1 offline/browser/live与live-browser在原evidence中通过；本轮完整P06离线回归通过，未重跑P04专属live流程 | `phase-p04→97e1972`不变；本轮不重打标签 |
| P05 | P05-fix1提交结算保护、订单硬校验、原请求与只读计划补修已记录 | P05-fix1 offline/browser及A04真实修订通过；P03前置门槛由P06-fix2的新9/9批次通过；本轮未重跑P05专属live流程 | `phase-p05→1ddfc7c`不变；本轮不重打标签 |
| P06-fix1 | F01–F08代码与反例测试已实现 | Windows offline 9/9、browser 2/2（E2E 9/9）；图表人工核对通过；报告解析通过，用户确认HTML报告显示正常；P03 live原始判定3/9，P003误报已修且其余仍失败；P05-A04 live通过。Linux完整离线CI run 40154211444 success | 实现及P03 gate补修已推送；P03严格门槛未关闭，不创建phase-p06-fix1；旧标签不动 |
| P06-fix2 | Task1–Task6补修、反例、模块文档与证据已实施并逐任务推送 | Windows offline 9/9、browser 2/2（E2E 9/9）、P03 live 9/9、Linux CI run 40165201596 success。正式真实后端浏览器下载及其他报告格式人工打开仍未验 | 已推送`7f69ff12a1a3d33d80b8e9a798c5bef65aa32de3`；P06严格门槛未关闭，无P06完成标签 |
| P07 | P07-fix1补修已实施，证据/状态/README更新 | offline9/9（191 unit/169 integration/38 frontend）、fake browser2/2（E2E11/11）、下载API5/5；P03固定3×3及P07 live为not_run，严格验收未关闭 | remote main与提交SHA核对一致；CI run40180805788的p06-offline job success；phase-p07→307edb4保持，不创建完成标签 |
| P08-fix1 | 已推送F01–F07补修及P07报告门槛独立改动 | offline9/9（212 unit/193 integration/38 frontend）、完整fake历史browser13/13、CI success（job为p06-offline，并非P08专属验收）；F01远程REST读取和F06自动分页部分开放，F08远程持久intent/对账与F09版本隔离未关闭；真实模型/ERP not_run | P08代码与证据已推送main；phase-p08→c2427e0不动，不创建完成标签 |
| P09 | F01–F07修复已推送；F08仍开放；F09部分验收 | offline 7/7、browser 16/16；新P03真实批次6/9，P09真实批次仅2/13外层尝试通过且有提交后失败；正式下载/全恢复矩阵及其他本地操作验收未完成 | F07/F08及失败轨迹/状态更新已推送；不创建phase-p09、不开始P10、不称生产上线 |

历史说明（该时点P03尚未补验，当前以顶部复核及阶段表为准）：P04-fix1 的离线、浏览器及P04真实模型验收通过；完整状态及限制见[P04补修计划](../implementation/P04-followup.md)和[evidence/P04-fix1.md](../../evidence/P04-fix1.md)。P03-A06仍未通过，所以不宣称TechnologyAgent MVP独立验收完成。P05、P06均按用户当时明确指令实施；P07及之后未开始。

phase-p04已存在并指向97e1972，标签只代表该历史提交，不代表本轮独立验收通过。所有旧标签保持；P03真实验收补齐前不宣称前置完成，P04补修用phase-p04-fix1。

## P04与前置阶段独立复核（2026-10-24）

- 基线97e1972：P04 offline exit0、9/9（425.21s），55 unit、115 integration、28 frontend；类型/构建/契约通过。Chrome browser exit0、2/2 manifest、8/8 E2E（61.71s），含真实服务重启；本轮服务已停止。
- 九项P04缺口：过期租约旧执行者仍提交；取消不生效；resume崩溃忽略checkpoint；写请求/决定重放不收敛；多供应商漏后续草稿；订单页与聊天状态失配；输入错误消耗中断；停用零件可下单；意图模型绕过幂等预算。
- 主审真实Mongo隔离探针复现上述关键状态，包括订单已提交但operation仍processing、取消后批准、4条checkpoint仍在却run失败、跨页面批准后聊天失败。额外唯一库已清理，开发库未reset；标准browser测试库按manifest重置并保留。
- P00/P01/P02原问题关闭。P03-R02/R03/R07仍部分未关；P04历史live manifest 2/2是seed+订单测试，不能替代P03固定三问各三次。本轮无供应商请求，不把历史live标成本轮通过。
- phase-p04=97e1972远程核对完成，不移动；phase-p03不存在。具体见[P04审查](../reviews/2026-10-24-P04-review.md)与[P04/前置补修计划](../implementation/P04-followup.md)。P05不开始。

## P03-fix1 补修与本地验收（2026-10-24）

- 修复范围：真实工具参数增量合并和提前 EOF；结构化事实数值/实体/范围/单位校验；正式正文校验后发布；每次调用受 run 总时限约束；同视图旧刷新隔离；逐消息历史模式；MCP 建立/发现失败清理；live 验收拒绝假通过且 manifest 非空。9 项只读工具、目录/协议边界保持不变，不写订单、不 reset 开发库。
- `uv run python -m scripts.verify_stage P03 --mode offline --report .runtime/reports/P03-fix1-offline.json`：exit 0，9/9；49 unit、92 integration、25 frontend；总计 181.72 秒。seed 只写 `technologyagent_test_p03_verify`；offline init 使用 `technologyagent_test_p03_offline`。
- `uv run python -m scripts.verify_stage P03 --mode browser --report .runtime/reports/P03-fix1-browser.json`：exit 0，E2E 7/7；新增延迟旧终态刷新后连续新运行用例通过。服务已停止，专用 browser DB 不存在。
- Live preflight：无 `MODEL_API_KEY`、`MODEL_NAME` 与 `RUN_LIVE_MODEL=1`；直接调用 `.venv/Scripts/python.exe -m scripts.verify_stage P03 --mode live --report .runtime/reports/P03-fix1-live.json` 返回 `not_run` / exit 2。真实 3×3 未执行，不伪报通过。
- 证据、确定性反例与当前远程/CI状态见 [evidence/P03-fix1.md](../../evidence/P03-fix1.md)。

## P04-fix1 与 P03 残留补验收（2026-10-24）

- P04 offline 最终复跑：9/9，65 unit、128 integration，前端 typecheck/test/build 与 contract_check 通过，总计419.88s；browser 8/8、67.95s，含服务重启与订单页→原聊天恢复。
- P04 live：隔离库订单2→3，审批消费、operation succeeded、run completed；P001新增55件，I001 inbound10→65、on_hand保持20。Live browser单测1/1：数量编辑至60件后经服务重启与订单页批准，独立隔离库新增1单，inbound10→70、on_hand20。
- P03-A06：4批各9次均记录，批次0/9、0/9、2/9、2/9；最终2/9。实现层字段/单位/范围、反向结论和截断用例离线通过，但真实模型对部分问题选错工具或输出不满足事实验收，故前置阶段未关闭。
- 完整P04修复清单、失败原因和真实事件轨迹见[evidence/P04-fix1.md](../../evidence/P04-fix1.md)、[P03-A06-live-traces.json](../../evidence/P03-A06-live-traces.json)、[P04-live-traces.json](../../evidence/P04-live-traces.json)。
- phase-p04=97e1972保持不动；由于P03-A06未通过，当前不创建phase-p04-fix1 / phase-p03。P05未开始。

## P05-fix1 与前置补验收（2026-10-24）

- P05-F01–F08 已实施：提交后 settlement 保事实、订单只读限次修订、原请求/查询依据/计划执行、结构化数值和最终答复门槛、决定历史/编辑字段、取消事实与跨恢复累计预算、UI 恢复展示及文档更新；新增确定性回归。
- `verify_stage P05 --mode offline` exit 0，9/9；98 unit、142 integration、34 frontend tests；typecheck/build/contracts通过，总计486.60s。`verify_stage P05 --mode browser` exit 0，2/2；E2E 8/8（67.14s）。
- P03固定真实模型3题×3次：6/9（题1、题3通过3/3；题2失败3/3，原因包括有效预览缺失、最终回答遗漏、执行流错误/持久视图不一致）。9条完整脱敏请求、工具/事件、验收结果与DB前后快照保存在本地忽略轨迹中，失败不删、不统归模型。
- P05真实库存Harness 1/1、订单审批/恢复1/1、P05-A04真实模型有限修订1/1。A04注入一次受控语义遗漏，live模型补正文并通过；订单2→3、成功操作8→9、已消费审批8→9，P001/W01 inbound10→65、on_hand20不变。live聚合清单未重新运行，避免重放已固定执行的P03 3×3调用。
- fix1实现提交与证据更新提交均已推送；远程 main SHA核对一致，两次GitHub Actions CI均success。SHA与run链接见[evidence/P05-fix1.md](../../evidence/P05-fix1.md)。phase-p04/phase-p05及其他旧标签不移动。P03-A06未关闭，因此不创建 `phase-p05-fix1` 或补造 `phase-p03`，不开始 P06。
- 逐项证据与轨迹位置见[evidence/P05-fix1.md](../../evidence/P05-fix1.md)。

## P03 与前置阶段独立复核（2026-10-24）

- 基线 4efc643：offline exit0、9/9（176.86s），37 unit、86 integration、23 frontend；typecheck/build/contracts通过。Chrome browser exit0、6 E2E（manifest16.47s）；独立测试库与本轮服务已清理。
- 9项缺口（3 P1/6 P2）：工具分片未重组、数值不核事实、live验收可假通过且入口为空、违规结论先发布、最后调用超总预算、同视图旧刷新覆盖新运行、提前EOF伪成功、历史模式错标、MCP发现失败未清理。
- P00/P01维持关闭；P02-R01/R03/R04/R05/R06复核关闭，R02部分重新打开。原phase-p02-fix1→d493ca5已核对，不移动。
- 真实模型仍not_run，未请求供应商。无Key不是唯一剩余条件；补修后仍须严格3问题×3次真实轨迹与事实对照，满足后才创建phase-p03。
- 详细反例与证据：[P03审查](../reviews/2026-10-24-P03-review.md)；当前实施入口：[P03补修计划](../implementation/P03-followup.md)。P04不开始。

## P03 实际检查（2026-10-24）

- T01：OpenAI-compatible ModelPort；token/tool_call 增量/usage/无 usage/供应商错误/超时 fixture 通过；Key 未知时不冒充 live。
- T02：真实 FastMCP 子进程，9 工具 list/call；P001 15/25/55；Q02/60500、7 天 Q01/66000；每 run Bearer token，owner/run 不进入工具 schema；并发 header 不串。
- T03：LangGraph model→tools→model；脚本模型验证工具结果回传、未知工具/非法参数、订单结论拒绝、模型次数上限；MCP 断线/超时返回错误。
- T04：run_started 写入 model_mode；token/tool_started/tool_finished 沿用 P02 事件；工具卡显示参数/结果/source/call_id；fake 页明确 ScriptedModel。
- T05：成功 ToolResult 收集 call_id/entity/id/as_of；无依据业务数字/“已下单”拒绝；跨 run 不复制 evidence。
- T06：tests/live/test_readonly_agent.py 需要 RUN_LIVE_MODEL=1 + Key/name；当前 skip。verify_stage P03 --mode live 返回 not_run（exit 2），没有 9 次真实轨迹。
- 验证：**37 unit、86 integration、23 frontend、6 E2E**；offline 9/9（159.62s），browser 1/1（13.75s）；MCP smoke 9 tools。
- 未运行：真实模型、真实 ERP、订单写、专家、技能、沙箱；P03-A06 未通过，不能宣称阶段完成。
- GitHub Actions run [40064607521](https://github.com/newerwell/technologyagent/actions/runs/40064607521) **success**；仅 offline。
- 证据：[evidence/P03.md](../../evidence/P03.md)；截图：[P03-chat.png](../../evidence/P03-chat.png)。

## P02-fix1 实际检查（2026-10-24）

- F01/R01：删除不再事务外预查；事务内条件认领 `deleting` 与 `claim_thread` 竞争。确定性测试：idle→删除读后暂停→新 run 提交→删除 409，run/message/event/thread 保留；删除成功后再创建 404。
- F02/R02：useChat 统一 viewGeneration；select/newChat/refresh/unmount 使旧 load/recover/refreshAfterRun/SSE 回调失效；useSSE 每连接独立控制器。hook 覆盖 A/B、newChat、旧 reject、旧 abort 不释放新发送。
- F03/R03：send 在首个 await 前同步占用 sendToken/sending；ensure pending 两次 send 只启动一个流；浏览器预检查锁验证只 1 个 chat stream。
- F04/R04：budget 在 run_started 前注册；写完后执行器启动前读取持久 cancel_requested。窗口取消测试事件仅 run_started/run_finished/stream_end，无 token/tool。
- F05/R05：事务每次重查 request/hash；已有 idle thread 两同 request 首查空后竞争返回同 run、一个 just_created、唯一 user message。
- F06/R06：stream_run_events 终态后按 last_seq 排空；首批空/缺 stream_end 仍补出唯一末事件。
- 修复前旧提交临时 worktree：backend 3 failed（R01/R04/R05）+ R06 ImportError；frontend hook 4 failed/1 passed。详见 evidence。
- 验证：**33 unit、78 integration、23 frontend、6 E2E**；offline 9/9（163.84s），browser 1/1（27.83s）；contracts check exit 0。
- GitHub Actions run [40061149309](https://github.com/newerwell/technologyagent/actions/runs/40061149309) 已触发，branch CI badge `passing`；最终记录提交后核对 phase-p02-fix1。
- 未运行：真实模型/MCP/订单写/ERP/沙箱；FakeAgent 保持。

完整证据：[evidence/P02-fix1.md](../../evidence/P02-fix1.md)。

## P02 与前置阶段独立复核（2026-10-24）

- 本轮基线 d8415ce：P02 offline exit 0、9/9（151.81s），31 unit、74 integration、17 frontend；类型/构建/契约通过。74 integration 包含 P00/P01 回归。
- 独立测试库启动本机服务，同源 health/ready 通过；Chrome 4 E2E passed，browser manifest exit 0、1/1（18.05s）。服务与独立临时库已清理。
- P00 原两项维持关闭；P01 默认 seed 保护、在途/预警、预览请求代次、会话刷新四类问题关闭。
- 新增 R01–R06：删除会话与创建竞争导致运行记录丢失；旧会话响应污染当前视图；会话预检查前发送未互斥；预算注册前取消丢失通知；已有 thread 相同请求并发返回 409；SSE 终态竞态漏末事件。
- R01/R05 真实 Mongo 隔离探针复现，R02/R03 实际 hook 与真实 Chrome 补证，R04/R06 服务/路由内存调度探针复现。全部需正式回归和补修，不能以基础测试通过关闭。
- 远程原标签已核对：phase-p00=419ab23、phase-p00-fix1=bdbf2ea、phase-p01=2328263、phase-p01-fix1=9d6faf9、phase-p02=d8415ce；均不移动。下一交付标签 phase-p02-fix1。
- 详见 [审查报告](../reviews/2026-10-24-P02-review.md) 与 [补修任务/实施提示词](../implementation/P02-followup.md)。P03 不开始；真实模型等后续功能未验证。

## P02 实际检查（2026-10-24）

- **T01**：`contracts/events.py` 12 类事件/payload 校验；`fixtures/events/v1.json`；生成 `events-schema.v1.json` 与 `frontend/src/lib/events.ts`，`--check` exit 0。
- **T02**：threads/runs/messages/events + 唯一索引；创建/认领/user message 原子；10 并发 append seq 1..10；finish 固定 assistant id、run_finished/stream_end、状态/thread 释放同事务；transient write conflict 有界重试。
- **T03**：FakeAgent 示例 token/只读假工具；任务强引用与 SSE 分离；断开观察后 run 仍完成；Next rewrite 会缓冲 SSE，新增 `/api/chat/stream` route handler 直通 ReadableStream。
- **T04**：conversation/run/events/cancel；request_id 幂等、同 thread 不同请求 409；cancel=flag+预算通知；启动遗留 run 标 failed/PROCESS_RESTARTED；owner 条件进 DB 查询。
- **T05**：SSE 解析器覆盖中文每字节切点/CRLF/注释/多行 data/不完整帧/版本；reducer run+seq 去重、message_id 合并；`/chat` 有 FakeAgent 标识、历史、刷新恢复、停止、切换。
- 测试：**31 unit、74 integration、17 frontend、4 E2E**；P02 offline 9/9（296.72s），browser 1/1（23.94s）。P00/P01 回归包含在 74 integration。
- 未运行：真实模型、MCP 产品、订单写、ERP、沙箱；P02 明确 FakeAgent。
- GitHub Actions P02 run [40056732982](https://github.com/newerwell/technologyagent/actions/runs/40056732982) success；phase-p02 标签在最终记录提交后核对。
- 完整命令、A01–A06 映射、截图见 [evidence/P02.md](../../evidence/P02.md)。

## P01与前置阶段独立复核（2026-10-23）

对2328263运行`verify_stage P01 --mode offline --report .runtime/reports/P01-review-offline.json`，9/9通过、exit0，约222.3秒，含P00真实代理链与A/B构建回归。原P00-R01/R02可关闭。

P01新增复现：默认seed将I001 inbound65/version2覆盖回10/version1、O001 shipped回submitted；fixture有7件无未收订单支撑的inbound且额外两条预警；预览旧响应/选择可失配；首次会话失败后刷新不重试。详见[审查报告](../reviews/2026-10-23-P01-review.md)。这些修复已由 P01-fix1 实现、交付，并在 2026-10-24 独立复核关闭；原报告保留历史。

## 规划者独立复核（2026-10-23）

对419ab23重新执行P00 offline，6/6检查通过（23集成、2前端、构建等）；该提交GitHub Actions run39954200129成功。另发现原检查未覆盖的两项问题：本机前端监听/代理来源边界，以及修改API_PORT后使用旧构建的代理目标。后者已用隔离服务复现。

**P00-F01/F02本轮独立复核已通过，原两项问题关闭。** 证据见[P00-fix1](../../evidence/P00-fix1.md)和本次P01审查报告；原phase-p00不移动，修复交付使用phase-p00-fix1。P01 原四类问题亦已在 2026-10-24 复核关闭；当前按 P03 审查处理新问题和 P02-R02 剩余窗口。

## P01 实际检查（2026-10-23）

- `uv run python -m scripts.seed --reset` 与再次 seed 均 exit 0；6/3/8/8/2/2 不翻倍；用户新增订单保留；manifest hash `670e478c…`。
- `uv run pytest tests/unit -q` exit 0，**25 passed**；`uv run pytest tests/integration -q` exit 0，**49 passed**。
- `uv run python -m scripts.verify_stage P01 --mode offline --report .runtime/reports/P01-offline.json` exit 0，9/9 checks，84.20s；`contract_check` exit 0。
- 前端 typecheck/test/build exit 0，4 前端测试 passed；`/data` 生成。
- Chrome headless：W01/名称筛选、W02 切换、7 天预览 Q01/55/66000、价格优先 Q02/55/60500；数据源 local_seed；页面无横向溢出；Cookie Strict。
- P01-A01..A06 全部通过；异常边界（422/404/空结果/缺失报价/缺失库存/非法库存/布尔金额）有测试。
- 未运行：真实模型、聊天、订单写入、MCP 产品、沙箱、ERP、Playwright E2E；P01 明确不实现。
- GitHub Actions P01 run [39966870327](https://github.com/newerwell/technologyagent/actions/runs/39966870327) 全部步骤 success；phase-p01 标签在最终记录提交后核对。

完整命令、退出码、截图和限制见 [evidence/P01.md](../../evidence/P01.md)。

## P01-fix1 实际检查（2026-10-23）

- **F01**：默认 seed 改 `$setOnInsert`，只补缺失固定记录；I001 inbound65/version2、O001 shipped/version2、合法 P001/W01 55 件新增订单与草稿在再次 seed 后保持；输出区分 `fixture_counts` 与 `database_counts`。
- **F02**：I004 on_hand15/inbound0、I006 on_hand12、I007 on_hand5/inbound0；精确预警集合仅 I001/I005；未关闭订单剩余量与所有 inbound 逐项对账，完成/取消不计，fixture 不满足在写库前拒绝。W01 summary 107/99/109/101/2，总计 177/164/174/121/2。
- **旧基线迁移**：`repair_p01_baseline.py` 默认 dry-run，`--apply` 事务更新 I004/I006/I007 并 version→2；修改库存或相关新增订单时拒绝。开发库 `technologyagent_dev` 只读检查为 0 条，未 reset、未修正、未写入。
- **F03/F04**：预览用 requestId + catalogGeneration，旧成功/失败/finally 不回填；翻页只取库存不清 parts；目录/参数变化清预览；会话 loading/ready/error 分离，首次失败刷新可重试，401 只用户触发现有界恢复。
- 测试：25 unit、59 integration、12 frontend；`test_seed.py` 9、迁移 4、DataPage 5、Preview 5。验证前先得到 4 个 seed 失败、4 个 Preview 失败、2 个 DataPage 失败，再修复。
- `verify_stage P01 --mode offline --report .runtime/reports/P01-fix1-offline.json`：exit 0，9/9，165.45s；`export_contracts --check` exit 0。
- Chrome：首次 `/api/session/me` abort→错误→刷新恢复；延迟 W01 preview 后切 W02 不回填；预警 2 条且无 P004；605→改交期清空→7 天 660；P003 翻页后选择/结果一致，改 P001 清空；无横向溢出，Cookie Strict。
- 未运行：真实模型/聊天/订单写/MCP/沙箱/ERP；开发库未应用旧基线修正（业务 collection 为空，无需修正）。
- GitHub Actions P01-fix1 run [39980552764](https://github.com/newerwell/technologyagent/actions/runs/39980552764) 全部步骤 success；phase-p01-fix1 标签在最终记录提交后核对。

完整命令、修复前失败证据、浏览器结果见 [evidence/P01-fix1.md](../../evidence/P01-fix1.md)。

## P00-F01/F02 补修结果（2026-10-23）

- **F01**：Next dev/start 与 API 均只监听 127.0.0.1；Uvicorn 加 `--no-proxy-headers`；本地会话增加回环 peer + Host 白名单 + 前端 Origin 白名单；Cookie 统一 SameSite=Strict。
- **真实链路**：`uv run pytest tests/integration/test_local_startup_boundary.py -q` exit 0，1 passed；真实 Uvicorn + Next dev 下正常会话可创建/读取；恶意 Origin、伪造 Host、非回环 peer 均 403；`X-Forwarded-For` 不改变 peer；本机非回环 IPv4 连接 3130/8130 均失败。
- **F02**：`start.ps1` 每次新启动前端都按当前 API_PORT 构建，构建目标写入 `.runtime/frontend-build.json`；启动成功必须通过经前端的同源 `/health` 与 `/ready`；配置变化未停旧进程时拒绝启动。
- **构建 A/B**：`uv run pytest tests/integration/test_startup_configuration.py -q` exit 0，3 passed；两次构建的 rewrite 分别指向 A/B API_PORT。
- **启动 A/B**：API 8130→8131、前端 3130：两次启动 exit 0；同源 health/ready 通过；B 的 routes-manifest 指 8131，直连 8130 失败；同配置重复启动进程数仍 2；运行中改端口被拒绝；停止后端口关闭、marker 删除、测试库删除。
- **全量**：`uv run pytest tests/integration -q` exit 0，**31 passed**。
- **Chrome**：默认端口 + 测试库打开页面 200；local-owner 会话建立；Cookie HttpOnly/**SameSite=Strict**；仅未登录 401 控制台记录。
- fix1 commit `59d98e3` 已推送；GitHub Actions run [39959955218](https://github.com/newerwell/technologyagent/actions/runs/39959955218) success；旧 phase-p00=419ab23 保持不变；phase-p00-fix1 指向最终记录提交。

## P00 实际检查

- `uv sync --frozen --group dev` exit 0；`npm --prefix frontend ci` exit 0。
- `uv run python -m scripts.init_db` 连续两次 exit 0；replica set `ta-rs`、primary=true、schema_version=1。
- `uv run python -m scripts.check_compatibility` exit 0；8/8 探针通过（FastAPI/LangGraph/假 tool loop/ChatOpenAI 构造/Mongo 事务/Mongo checkpointer/FastMCP HTTP/DeepAgents 假图）。
- `uv run pytest tests/integration -q`：23 passed，exit 0；事务测试使用真实 replica set，不使用 mock。
- `npm --prefix frontend run typecheck`、`run test -- --run`（2 passed）、`run build` 均 exit 0。
- `uv run python -m scripts.verify_stage P00 --mode offline --report .runtime/reports/P00-offline.json` exit 0；6/6 checks passed。
- Chrome headless 打开 3030：页面显示后端已连接、就绪、local-owner 会话；原验收 Cookie 为 HttpOnly/SameSite=Lax，P00-F01 起统一为 **Strict**。DB 停止后 /ready 503，页面显示“降级/不可用/会话不可用”，保留“重新检测”，不无限 loading。
- `start.ps1` 在项目目录和另一个工作目录各运行一次：第二次不重复开进程；`stop.ps1` 后 8030/3030 均关闭。
- GitHub Actions `.github/workflows/ci.yml`：run [39953759929](https://github.com/newerwell/technologyagent/actions/runs/39953759929) 全部步骤 success；首轮 run 39950310945 在 init_db 失败，已由 `1d1acb9` 改用 compose 启动 Mongo 并修复。
- P00 交付时 Playwright E2E 未运行；P02 已新增并通过 4 个 chat E2E。真实模型/MCP 产品/沙箱/ERP 未实现，分别属 P03/P06/P08。

完整命令、退出码、环境、截图路径与已知限制见 [evidence/P00.md](../../evidence/P00.md)。

## 规划基线检查（历史）

初始规划阶段已执行：19个Markdown文档读取与相对链接检查通过；10个阶段均包含Git交付清单及对应phase-pxx标签；配置、依赖、运行目录的Git忽略规则检查通过。该检查只证明文档结构，不证明产品功能。

P00 交付时补充执行：`docker compose config` exit 0、CI YAML 解析 exit 0、`git diff --check` exit 0，并审查暂存路径排除 `.env`、`.runtime`、`mongo-data`、`node_modules`、`.next`、`.dsh-meow`。
