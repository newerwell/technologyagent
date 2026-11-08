# TechnologyAgent 剩余目标实施计划（2026-11-08）

> 最新入口：[R4后复审修订计划](P09-remaining-after-R4-review.md)。R0/R1已实施，R2–R4主体已推进；本文件保留原要求，不再作为从R0开始执行的当前状态。按新计划补A1–A4后继续R5–R9。

> 给实施 Agent：使用 executing-plans 按卡顺序执行。每卡先读取实际代码、观察反例，再修复、定向回归、更新证据与交接、显式提交推送。一次只实施一张卡；本卡未通过不推进下一卡。本文规划完成不代表功能完成。

**目标：**在保留用户数据的前提下补齐任务卡3、任务卡1边界和任务卡4–11，使本地完整采购Agent满足P09原验收，最后交付phase-p09；不开始P10。

**架构：**沿用Next.js、Python共享业务服务、Mongo事务、MCP及版本化Agent；只修现有缺口，不重写工程。测试Mongo另建容器/数据卷，API、MCP、测试和重启子进程指向同一个隔离实例。

**规格依据：**原[P09-final-closure](P09-final-closure.md)、[共享契约](../specs/CONTRACTS.md)、[最终场景](../specs/FINAL-ACCEPTANCE.md)。本计划替代2026-11-08以前的“下一步安排”，不降低原规格。

## 1. 已核对的起点与工作约束

- 工作目录：`C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent`。当前HEAD为`3d4b4ba04d655747f566260dc12ac00273adad29`，执行前重新检查HEAD、status、远端main及阶段标签。
- Docker29.9.2已运行，现有technologyagent-mongodb健康，27027映射27027，绑定原mongo-data。不得复用、重置、迁移或删除这份数据。本计划不再沿用“Docker未启动”的旧阻断结论。
- 任务3已补fake初始说明和肯定收货反例，证据记274 unit通过；8项真实Mongo集成未进入测试体。先补验，不机械重写这两项修复。
- 任务1有库存场景已修；剩余缺库存时漏part_inactive。任务2核心正文保留修复已存在，后续需完整链路验收。
- local_seed只用合成fixtures验证采购闭环；local_snapshot只读用户库存。原文件/副本72条、72物料、6仓位；缺预留/在途/目标/报价仍未知，不补造。
- 真实ERP不调用，写capability保持关闭；F15/F16可独立not_run。远程本地模拟器与持久对账仍是本次必做工作。
- 使用PowerShell7。写测试只允许technologyagent_test_*库。禁止git add .、reset --hard、clean、force push、删除原始数据。私有.env、JSON/metadata、日志、DB、依赖和下载文件不提交。
- 每卡维护evidence/P09-fix4.md与docs/delivery/HANDOFF.md，清楚区分实现、定向通过、全量通过、未运行和环境失败；不把8个夹具错误写成8个产品反例。

### 文件职责与新增接口

| 职责 | 实施位置与接口决定 |
|---|---|
| 隔离测试基础设施 | 新增根目录compose.p09-acceptance.yaml；新增scripts/p09_acceptance_env.ps1，供当前PowerShell用点号加载测试环境，不保存密钥 |
| 启动配置 | start.ps1只修“缺失变量”和“显式空变量”的区分；使用COMPOSE_FILE/COMPOSE_PROJECT_NAME选择隔离compose，不另造第二套应用启动器 |
| 模型调用 | services/model_observation.py新增内部ObservedModelResponse与collect_model_response；四入口共用，外部SSE默认保持原契约 |
| 报告范围 | 请求约束新增all_warehouses=False；选择器和核验器消费同一结构；实际MCP补snapshot_id，不换已有文件快照身份 |
| 版本隔离 | versions/v1_impl.py、v2_impl.py分别持有状态/节点/builder/config；versions/v1.py与v2.py为对应版本公开入口；安全业务服务继续共享当前实现 |
| 远程读写 | 新增services/provider_queries.py统一查询、services/remote_operations.py协调远程一次dispatch；operations仓储增加专用远程认领/标记方法，复用集合及唯一索引 |
| 验收 | 复用现有unit/integration/e2e/live；新增测试只覆盖缺口，不能伪造成功业务/下载响应；模块README、契约、蓝图同步 |

### 最终复审重点

1. 重启或干净检出后，服务不能因.env覆盖而切回快照/旧库。
2. 已提交订单说明失败不能重新下单；未知远程结果不能自动重发POST。
3. 所有仓库、中文仓位、原始数字物料ID不能被默认W01或P前缀改写。
4. 修改v2编排不能改变旧v1待审批checkpoint的恢复行为。
5. 测试绿灯必须对应真实调用入口、文件字节和数据库事实，不能把替身/解析/链接断言扩大成完整闭环。

## 2. R0：隔离环境与任务卡3补验

**对应原卡：**0的集成缺口、3的真实事务门槛。此卡先完成，不动原数据。

- [ ] 读取现有compose/start/config及集成夹具。只读检查27028端口、下述容器和卷是否存在；冲突则停下核实归属，不能删除不明资源或悄悄换端口。
- [ ] 新compose固定project=`technologyagent-p09-acceptance`，service=`mongodb`，container=`technologyagent-p09-acceptance-mongodb`，image沿用`mongo:8.0`。mongod端口27028、replSet=ta-rs，映射仅`127.0.0.1:27028:27028`。
- [ ] 使用全新命名卷`technologyagent-p09-acceptance-mongo`挂到/data/db；不得有mongo-data bind，不与旧卷共用。成员公布`localhost:27028`。仅对此隔离实例做首次初始化；health必须证明setName=ta-rs且isWritablePrimary=true。
- [ ] scripts/p09_acceptance_env.ps1提供`-Mode offline|browser|live`参数。第一次加载时保存本进程原有相关环境变量（包含是否存在），后续Mode切换不得覆盖这份原始快照；支持`-Restore`恢复。用脚本自身位置解析所属检出根目录，不能硬编码原工作区，使干净clone可独立使用。不把保存的密钥值输出或写文件。
- [ ] 该脚本设COMPOSE_FILE为新compose绝对路径、COMPOSE_PROJECT_NAME为上述独立project；MONGODB_URI与MONGODB_TEST_URI均为`mongodb://127.0.0.1:27028/?replicaSet=ta-rs&directConnection=true`。
- [ ] Mode分别设置原manifest固定库：offline=`technologyagent_test_p09_verify`、browser=`technologyagent_test_p09_browser`、live=`technologyagent_test_p09_live`；四模块source=local_seed，INVENTORY_SNAPSHOT_PATH显式空。fake/RUN0用于offline/browser，live/RUN1只用于live。
- [ ] 给start.ps1添加反例：环境变量显式空时不得从.env重新填回；只在变量不存在时导入。保留默认用户启动行为。测试用合成.env，不读写真实密钥。
- [ ] 为测试辅助脚本验证URI、DB、compose路径和子进程继承；错误模式/非test库在启动前拒绝。E2E重启继续使用继承的COMPOSE_FILE和两条Mongo URI。
- [ ] 执行compose config，确认挂载独立，再启动新mongodb，inspect实际挂载、端口及hello。验证一次真实事务写入/回滚，目标只用独立临时test库。

**实际命令（新增脚本/compose实现后）：**

```powershell
Set-Location -LiteralPath 'C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent'
$batch = Get-Date -Format 'yyyyMMdd-HHmmss'
. .\scripts\p09_acceptance_env.ps1 -Mode offline
docker compose config
docker compose up -d mongodb
uv run python -m scripts.init_db
uv run python -m pytest --basetemp ".runtime/pytest-R0-$batch" `
  tests/integration/test_order_review_loop.py `
  tests/integration/test_order_settlement_failures.py `
  tests/integration/test_inventory_snapshot_routes.py -q -rs
$LASTEXITCODE
```

**通过条件：**原8项订单测试及快照路由测试均进入测试体并通过，实际数量按收集结果记录，不固定伪报9项。确认三种结算路径一张订单/一个成功operation，I001 inbound10→65、on_hand20，正确保存55套、66000分、用户7天/报价5天及来源时间；fake无模型正常完成，错误数量/金额/单位拒绝，明确否定收货可通过，连接失败/耗尽不重新写单。发现真实产品失败就在本卡红→绿修复，不跳过。

**提交：**`test(p09): isolate replica set and verify committed order settlement`。只提交compose、辅助脚本、必要启动修复/测试/README及证据，核对远端SHA。新卷保留供后续验收，不删除原卷；也不把此提交称P09完成。

## 3. R1：补完停用物料边界

**对应原卡1；入口services/replenishment.py。**

- [ ] 先加`test_inactive_part_without_inventory_reports_both_reasons`：物料active=False、该仓库存不存在，missing_fields同时含inventory和part_inactive，不能actionable。
- [ ] 看见旧代码缺标识失败后修复缺库存分支。不得给未知库存补真实事实；只增加停用原因。已有完整库存场景继续保留available15/projected25/shortage55。
- [ ] 再覆盖同物料启用恢复推荐、混合批次独立判断、停用草稿409且无新草稿/订单，前端停用中文原因。
- [ ] 跑test_replenishment_service.py、test_replenishment.py及ReplenishmentPreview对应前端测试；更新证据、提交推送。

**通过条件：**所有停用行不可采购，缺原因问题关闭，已有正常补货结果不变。

## 4. R2：统一模型调用、预算和有限重试

**对应原卡4。**

- [ ] 先补模型观察测试，使用脚本异步流和固定/可控单调时钟，不请求真实模型。
- [ ] 新增内部`ObservedModelResponse(deltas, successful_call_id, usage)`和`collect_model_response(model,messages,tools,ctx,budget,emit,purpose)`。成功只返回完整成功尝试的delta集合；失败缓存不得拼进成功答案。
- [ ] 主图model_node、semantic_review（包括emit=None）、_live_draft_request、_revise_order_answer全部接入；删除它们重复charge与start/finish。emit=None使用空回调，但保留预算/取消。
- [ ] 每次尝试按取消/期限→charge_model→started→请求→finished执行；失败和成功各自唯一call_id，主图工具parent绑定successful_call_id；usage缺失保持None。
- [ ] 逻辑期限首次计算为min(60秒,run剩余时间)，第二次不重置。无delta等待也轮询取消/期限，关闭未完成流与等待任务。
- [ ] 最多额外一次：仅首delta前传输中断/超时；httpx.RemoteProtocolError纳入。已收到任意token/tool_call/usage不得重试。协议内容错误、401/429/5xx、截断、取消和预算耗尽不重试，不只看retryable标志。
- [ ] 覆盖首失败后成功计2次、连续失败仅2次、三种delta后失败只1次、预算不足/取消不启动第二次、失败片段不泄漏、工具只触发一次、trace不双计数。
- [ ] 定向回归model_observation、model adapter、semantic_review、graph和order_review相关测试，证据后提交推送。

**通过条件：**实际请求计数=预算计数=trace尝试计数；不重放工具或订单工作流。

## 5. R3：报告实际入口、范围与来源

**对应原卡5。三个子步骤在同一卡依次实施。**

- [ ] 5A先在真实注册的MCP客户端调用inventory_page/warning，复现seed页缺snapshot_id，而不是只测旧helper。服务层返回成功后，对完整筛选集合生成内容快照并证明当前页属于它；无法证明或发生漂移返回明确错误。
- [ ] 文件快照继续使用原文件身份/采集时间及未知完整性。不要常量ID，不把每页as_of差异当内容变化。测两页完整可合并、as_of不同可合并、变动/缺页/重复实体拒绝。
- [ ] 5B请求约束增加all_warehouses=False，以来源目录真实名称/ID解析中文仓位和数字物料ID。全仓标记优先于存储默认仓库，明确单仓也覆盖偏好。
- [ ] 数据集选择与报告核验消费同一结构范围；删除各自独立的Wxx/Pxxx正则判断。全仓拒单仓筛选，单物料不得多物料；快照“全部”仅表示保存集合。
- [ ] 测全仓+W01失败/完整集合通过、保存W01后全仓不回填、中文仓位错/对、数字ID保持原样及单物料额外实体拒绝。
- [ ] 5C实际MCP快照报价/补货不支持错误继续拒绝，但metadata保持snapshot来源和采集时间；供应商等实际seed模块仍标seed。
- [ ] 使用真实artifact_report入口生成文件，回读范围/来源/金额后才report_verified。回归snapshot、analysis_artifact、report_scope及实际MCP相关测试，提交推送。

**通过条件：**真实MCP查询可用于完整报告；范围不能被默认值扩大/缩小；无伪造来源。

## 6. R4：冻结v1并接入真正的版本路由

**对应原卡6，基于R2/R3之后当前安全修复的实现提取。**

- [ ] 保留旧checkpoint fixture字节不变，先记录hash。先添加“修改v2节点/状态/边后旧v1仍原样恢复”的失败测试，不能用函数自相等证明隔离。
- [ ] v1_impl持有独立v1状态、主图节点/builder、订单节点/builder、workflow_config及编排辅助代码；v2_impl持有独立v2编排。v1.py/v2.py只导出对应实现，不能指向同一共享builder。
- [ ] GraphExecutor与OrderWorkflowService._graph按持久graph_version真实选择入口；保持旧字段默认、节点名、thread key、namespace和中断恢复ABI。
- [ ] 审批、权限、预算、事务、Provider写能力、幂等继续复用当前安全服务；不从旧tag恢复漏洞，也不复制第二套业务写逻辑。
- [ ] 测旧fixture批准成功、重复恢复仅一单、改变v2不影响v1、新v2 namespace、两版本互不覆盖。原fixturehash不变，更新模块README与兼容证据，提交推送。

## 7. R5：远程读取统一接入

**对应原卡7A，仅持续运行的本地HTTP模拟器。**

- [ ] provider_queries服务作为API和MCP的共同入口。保留ErpClient现有协议，不猜真实ERP地址/字段；只在具备严格映射后移除对应API的remote门禁，不能回退Mongo再标ERP。
- [ ] 按既有Part/Supplier/Inventory/Order DTO校验完整必需字段。缺字段返回明确错误，不造0、单位、版本或完整实体。
- [ ] 聚合校验page/page_size/pages/total、记录数量、实体ID、重复页/实体；最多100页/10000条，并扣减原调用剩余预算。按原手册保守门槛，缺页、矛盾或达到页数/记录上限时明确不完整，不返回“全量成功”。
- [ ] 模拟器测试API/MCP同输入同结果、严格缺字段拒绝、正常两页、重复/越界/total异常/预算耗尽。禁止真实ERP请求；更新README/契约、提交推送。

## 8. R6：远程一次dispatch与持久对账

**对应原卡7B/7C。需要R5，但真实写capability仍关闭。**

- [ ] 为operations新增远程专用一次认领及dispatch方法。内部action包含稳定provider范围+原业务action，沿用owner/action/key唯一约束，不改变本地旧索引。
- [ ] provider范围由配置端点规范身份稳定派生（剥离认证/查询片段），不能来自模型或每次随机值。保存原action、provider范围、规范payload hash、审批关联、关联号、dispatch标记、外部结果/ID。
- [ ] 复用服务器审批验证：owner/action/payload/版本一致，不能只检查approval_id存在或相信approved=True。审批与operation的一次关联按当前消费规则原子保留。
- [ ] 新认领胜者原子写dispatch并获持久确认后才可POST一次。已有operation永不自动再POST，包括lease过期、服务重建和崩溃恢复；同键异payload冲突。
- [ ] dispatch后超时、取消、HTTP/JSON损坏、解析失败、进程崩溃、保存结果失败都进入待对账；不靠client内存集合保证幂等。
- [ ] reconciliation先分远程，只lookup；普通404、超时或关联不能核实继续unknown。不得因没有本地订单返回retryable。本地事务恢复路径保持原安全语义。
- [ ] 真实Mongo+持续HTTP模拟器计数：并发请求POST≤1、丢响应后重建服务lookup同一单仍POST1、dispatch后崩溃恢复不重发、损坏JSON/保存失败unknown、404unknown、owner/provider隔离、异payload冲突。新增跨进程恢复测试，不用单个client计数替身冒充持久性。
- [ ] 更新接口/模块README和证据，提交推送。F15/F16仍not_run，不声称ERP联调完成。

## 9. R7：补23工具逐项证据

**对应原卡8。**

- [ ] 依据P08_REFERENCE_TOOL_NAMES列出原23项（15读、8写）；另有内部工具不能顶替其中任何一项。
- [ ] 在真实MCP客户端测试正常及非法输入。非法参数实际发到服务端，不能只jsonschema.validate。
- [ ] 写工具各自测未批准拒绝、批准成功、相同键重放、错误owner/过期版本拒绝；复用已有业务fixture与审批/收货/改单测试，不重写业务。
- [ ] 每工具记录正常/非法输入、实际MCP结果、具体DB前后记录/数量/库存/operation/流水变化、测试名。只查到部分集合时如实说明，不能称全库相同。
- [ ] 23项都具正常业务证据才关闭F13；矩阵作为脱敏摘要提交，原始运行日志忽略。提交推送。

## 10. R8：双尺寸真实流程与格式打开

**对应原卡9前半。**

- [ ] 两套viewport固定1440×900、390×844，workers=1。每个尺寸独立执行查询→实际报告→真实下载→草稿→编辑数量/金额→刷新待审→重启恢复→批准→重复批准。
- [ ] 下载核字节数、SHA256、解析内容/业务值、来源、owner/run归属；不能route.fulfill伪造成功业务/文件。允许abort/延迟做故障注入。
- [ ] 固定案例55套/660.00元，改60后720.00元；刷新和后端重启后保留最新版本，批准后相同单号/ID、仅一张新增订单与一个成功operation，inbound与流水按实际规则核对。
- [ ] 重启helper必须继承R0两Mongo URI、COMPOSE_FILE、project、数据库、source和model flags；不能重启后读旧数据。
- [ ] 保留既有三图/HTML确认，补MD/CSV/JSON实际打开记录；每截图对应文件名/hash和同批次文件。没有打开能力就not_run，解析不顶替打开。
- [ ] 更新E2E、矩阵与证据，提交推送。F09/F17只按真实覆盖关闭。

## 11. R9：完整门禁、CI、干净检出与最终标签

**对应原卡9后半、10、11，前述卡均通过后执行。**

- [ ] CI增加P09 offline：使用R0隔离compose、27028的两Mongo URI、MODEL_MODE=fake、RUN_LIVE_MODEL=0、四模块local_seed、快照路径为空及technologyagent_test_p09_verify；运行run_acceptance local/offline并上传报告。保留需要的原P06检查，不把P06success称P09success。CI不得用私有文件或live密钥。
- [ ] 明确修正FINAL-ACCEPTANCE中过度passed的F06/F09/F13/F17/F18及“23只读”表述；以新证据关闭，不抹去旧失败。
- [ ] 先完整offline，再browser，再固定live；每次生成新batch，检查所有子项退出码。live沿用13外层、P03内部9次、F12内部9组，不能增次挑成功。
- [ ] 将已通过修改与CI推送，核远端SHA及P09 CI实际结果。从该代码提交全新clone到`.runtime/p09-clean-<sha>`，不复制venv/node_modules/build，锁文件安装。
- [ ] 干净检出使用独立test库（如technologyagent_test_p09_clean_<batch>）和R0隔离Mongo，fake/seed执行报告下载、订单编辑、审批重启恢复及幂等闭环。此项不替代固定库的完整验收。
- [ ] 若干净检出或CI发现代码缺陷，回到对应卡修复；重跑受影响门禁并对最终代码SHA重新核对，不能用旧源码通过记录冒充新源码。
- [ ] 停测试应用，`p09_acceptance_env.ps1 -Restore`恢复原环境。确认DB=technologyagent_dev、原live设置、库存/物料local_snapshot及项目库存路径，其他值按原保存恢复；正常启动后页面/MCP各核72条且缺字段未知。
- [ ] 不执行down -v，不删除测试或原数据卷；测试证据保留。恢复日常启动不reset/seed用户库。
- [ ] 每卡已push且当前源码与验收源码一致；P06自身关闭后才补phase-p06；P09所有本地必需项、固定live、CI及干净检出均关闭后创建annotated phase-p09，核对远端解引用commit，旧标签不移动。

**完整门禁命令模板（R0脚本已实现）：**

```powershell
$batch = Get-Date -Format 'yyyyMMdd-HHmmss'
. .\scripts\p09_acceptance_env.ps1 -Mode offline
uv run python -m scripts.run_acceptance --scope local --mode offline `
  --report ".runtime/reports/P09-$batch-offline.json"
$LASTEXITCODE

# 仅offline全部通过后执行；切配置前先停本项目应用
.\stop.ps1
. .\scripts\p09_acceptance_env.ps1 -Mode browser
.\start.ps1
uv run python -m scripts.run_acceptance --scope local --mode browser `
  --report ".runtime/reports/P09-$batch-browser.json"
$LASTEXITCODE

# 仅browser全部通过后执行
.\stop.ps1
. .\scripts\p09_acceptance_env.ps1 -Mode live
.\start.ps1
uv run python -m scripts.run_acceptance --scope local --mode live `
  --report ".runtime/reports/P09-$batch-live.json"
$LASTEXITCODE
```

## 12. 每卡交付与最终完成条件

每卡定向pytest使用`--basetemp .runtime/pytest-<卡>-<batch>`。记录首次产品失败、修后命令/数量/退出码、DB事实、证据及限制；环境错误先修环境，不降低断言。

每卡完成执行diff检查、显式暂存本卡文件、cached检查、commit、push origin main、rev-parse/ls-remote核一致；推送失败保留提交并停止后续卡，不称已上传。工作区其他Agent的审查文档、截图、.dsh-meow和frontend/AGENTS不得顺手打包或清理。

最终必须同时满足：

- [ ] 原确认缺陷与本计划R0–R9全部关闭，任务2持久正文一致性完成完整验收。
- [ ] F01–F14、F17–F18达到原规格；各相应offline/browser/live实际通过，保留全部失败与成功。
- [ ] 23工具逐项事实、文件打开、两个尺寸和干净检出闭环证据齐全。
- [ ] 最终源码与验收源码一致，CI P09成功，本远SHA及必要阶段标签核对。
- [ ] 日常配置恢复且页面/MCP72条实际读取；原mongo-data、私有文件未被测试修改。
- [ ] F15/F16独立not_run，不宣称真实ERP联调或生产上线。

最终报告按原手册逐项列任务状态、反例、命令/数量/退出码、全门禁、DB变化、证据、SHA/标签及限制。任一必需项未达到，P09继续未完成，不开始P10。
