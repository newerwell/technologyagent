# TechnologyAgent R4后剩余目标修订计划

> 日期：2026-11-08。给实施Agent：本版是当前剩余工作入口，替代旧计划的起点和执行次序；原共享契约与最终验收要求保持。只做规划中的卡，不重写整个工程，不开始P10。

**当前源码：**b67c60a01ed8587e92dc59e2db30abb68f31f3fd，本地与GitHub main一致。开始时重新核对，不假定仍是该SHA。

**环境更新：**用户启动Docker后已重新只读核实：Docker29.9.2可连接；隔离容器healthy、仅绑定127.0.0.1:27028，/data/db使用technologyagent-p09-acceptance-mongo命名卷；hello为ta-rs且isWritablePrimary=true。本地Docker阻断解除，不重建副本集、不重做R0。GitHub runner的Mongo内核兼容问题仍按A4独立处理。

**目标：**保留已完成R0/R1及R2–R4主体实现，补本轮明确缺陷和验证缺口，然后实施R5–R9，完成本地必需场景、固定live与Git交付。

**依据：**[本轮复审](../reviews/2026-11-08-P09-b67-review.md)、[原完整实施计划](P09-remaining-implementation.md)、[P09最终补修手册](P09-final-closure.md)。每卡红→绿→定向测试→证据/交接→显式commit/push/远端核SHA；不得以绿灯替代未覆盖的业务事实。

## 一、先确认已完成部分，禁止无意义重做

| 原卡 | 当前处置 |
|---|---|
| R0 | 保留现有隔离compose、27028、命名卷和环境助手；原9项订单/snapshot集成本轮通过，不重新建库迁移原数据 |
| R1 | 停用物料缺库存标识已修，本轮全unit通过；不再安排同样的修复 |
| R2 | 保留统一collector、四入口、预算/trace和正常有限重试，只实施下面A1的错误分类/硬期限补修 |
| R3 | 保留真实MCP快照、全仓/数字ID/来源修复，只实施A2来源目录仓位补修 |
| R4 | 保留独立版本文件和已接入路由，原2项真实Mongo升级测试已通过；只补A3实际v2变化对照和必要策略边界 |
| R5–R9 | 尚未完成，继续执行后文任务，不降低任何原验收 |

隔离环境仍用`. .\scripts\p09_acceptance_env.ps1 -Mode offline`；MONGODB_URI/MONGODB_TEST_URI均27028/ta-rs，合成测试库。先hello检查PRIMARY，再决定是否启动已有专用容器；控制接口报错但Mongo可用时，不将其误写为standalone。不改原mongo-data，不重置日常库，不删除不明卷。

新增计划、原实施文档目前未被Git跟踪。下张交付显式纳入这两份规格、本轮复审及相应交接，保证新检出可读到实施依据；不要顺带提交其他未审查截图、旧审查文件或本机文件。

## 二、补修与强化验收：A1→A2→A3→A4

### A1：修完R2的HTTP分类与60秒硬上限

**修改入口：**integrations/model.py、services/model_observation.py；测试放现有test_model_adapter.py/test_model_observation.py。

1. 新增反例：HTTP401/429/500已收到headers，错误正文ReadTimeout。当前三者实际请求2次；修后都只能1次，错误保留MODEL_PROVIDER_ERROR和状态语义，不得转为可重试超时。
2. 新增反例：HTTP200损坏gzip/内容解码错误，以及HTTP500损坏正文。前者为MODEL_PROTOCOL_ERROR、不重试；后者保留已知HTTP错误优先级、不重试。错误诊断正文读取失败不得覆盖状态，也不得泄漏密钥或完整敏感正文。
3. 实现顺序：先固定status>=400分类；读取诊断正文是有限、可失败的附加信息。DecodingError等内容错误与TransportError/Timeout分别映射；不得宽泛HTTPError统一变MODEL_UNAVAILABLE。真正首delta前RemoteProtocolError/连接超时仍允许一次重试。
4. 增加可控时钟反例：timeout_seconds=120、run剩余300，模型61秒返回，当前成功；改为首次min(60,调用方期限,run剩余)后超时。两次尝试共同期限不刷新，timeout较小仍按小值。
5. 回归三种delta后断流不重试、401/429/5xx/协议错误不重试、连续传输失败最多2次、取消/预算不足阻止第二次、trace/实际请求/预算一致、工具只执行一次。
6. 跑上述两个测试文件、semantic_review、graph_answer_preservation和order_review_bounds；保留当前306全unit基线但数量以实际新收集为准。证据后提交推送。

**完成判据：**复审的错误状态反例每项仅1请求；61秒迟到结果不成功；合理传输重试和工具父call_id仍正确。

### A2：修完R3的来源目录仓位识别

**修改入口：**agent/harness.py、graph_versions.py及analysis范围使用方；来源目录由当前Inventory服务提供。

1. 首先用合成来源目录增加反例：`课程测试仓-A`与`A区-1号库`都能被完整识别；前者当前解析为空并允许W01错误数据。不要读取私有库存作为测试夹具。
2. 为请求解析增加可选只读来源目录上下文（warehouse labels、part IDs）；解析按来源真实名称做精确最长匹配，支持中英文/连字符/数字后缀，不硬编码六个私有名称。
3. 快照目录复用适配器已保存的metadata.warehouses和物料ID；seed目录从当前catalog/inventory服务取得。bootstrap注入可信目录读取回调；不向模型开放owner/provider选择，也不让模型提交自称可信的目录。
4. 在GraphExecutor和v2前置路由构造请求约束时传入同一目录上下文；工具参数约束、数据集选择和最终报告核验继续消费同一结构。未知明确仓位应提示范围不可核实，不得默认为“未指定”或套W01。
5. 测指定课程测试仓-A+W01数据失败、匹配数据通过，带连字符/英文数字后缀、多个名字前缀重叠、未知仓位、默认W01不覆盖明确仓位、全仓不继承单仓、数字物料ID不加P。
6. 回归原R3的63项与真实MCP入口，实际artifact_report生成文件、回读来源/范围/hash后才能report_verified。证据后提交推送。

**完成判据：**所有当前来源仓位均能精确匹配，错误仓位不能作为所请求仓位报告通过；A区修复、全仓和来源身份保持。

### A3：完成R4的实际版本变化验收

**保留：**v1_impl/v2_impl、独立订单实现及当前路由。旧fixture SHA256继续固定`1fd530124549641fd790a9e8a730db51e2c2b14dab6aa894f501e1dbb950a318`。

1. 当前test_graph_upgrade.py两项已在PRIMARY实例通过，不再把“未执行”作为当前状态。新增测试，不覆盖原fixture，也不只比较函数引用或将v2入口改为抛异常。
2. 在测试专用v2图中加入独有state字段`v2_probe`、独有节点并改变一条实际经过的边；通过真实执行入口确认该字段及节点事件确实出现。保留正常业务节点与审批/事务服务，不伪造API成功。
3. 保持这套v2变化有效，恢复原v1待审批fixture、批准及重复恢复；核对仍一张新增订单、一个成功operation、审批/库存事实及v1原namespace。
4. 同一测试运行变化后的v2并查独立checkpoint键；保存旧v1 checkpoint文档全量快照，结束时比较内容不变，不能只比ID数量。
5. 版本相关策略（节点/边/state、计划/阶段/修订规则）应由版本入口确定。GraphExecutor可共享执行机制，权限/预算/事务等当前安全服务继续共享；如真实反例证明某v2策略通过共同外层影响v1，只抽出该策略到版本实现，不机械复制所有公共helper或旧漏洞。
6. 运行graph_version_isolation、graph_answer_preservation、p07_specialists_skills、graph_upgrade，再跑订单review/settlement防回归；记录实际通过后提交推送。

**完成判据：**v2变化明确生效期间v1原样恢复，重放一单、旧checkpoint内容不变、两版本namespace独立。不能仅凭共享import断言失败，也不能仅凭builder对象不同断言通过。

### A4：先修CI环境，再继续后续功能

已实查run42448456550在Mongo健康检查失败、pytest未执行。日志为宿主kernel6.19+与当前Mongo不兼容；这是CI环境阻断，不靠增加健康等待或忽略错误修复。

1. 现有P06 job的runner由ubuntu-latest固定为ubuntu-22.04。官方当前runner说明内核为6.8；启动前打印并校验实际uname -r，仍处不兼容区间就失败保留日志，不能声称改label就完成。
2. 保持Mongo主版本，不降到旧小版本，不禁用Mongo启动保护、不改用户Docker内核。保留真实replica set、PRIMARY及事务要求。
3. 补Mongo health负向检查：非PRIMARY、错误setName、rs.status异常时命令必须非零；仅打印false不能证明健康失败。必要时只修隔离compose的显式exit判断，不能触碰原数据。端点已PRIMARY时不重复初始化。
4. 推送并等待新CI：Mongo启动、PRIMARY/事务、依赖安装和真正pytest均执行且通过后关闭本卡；原失败保留。没有兼容runner时停止此卡并报告，不能假装CI成功。
5. 新P09 offline job仍在R9完整补上，P06 job通过不替代它。

依据：[MongoDB内核说明](https://www.mongodb.com/docs/manual/administration/production-notes/)、[SERVER-121912](https://jira.mongodb.org/browse/SERVER-121912)、[GitHub Ubuntu22.04镜像说明](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2204-Readme.md)。这些是方案依据，真正完成仍以新run为准。

## 三、随后继续R5–R9

下面沿用原计划的行为、接口、测试与完成条件。实施顺序R5→R6→R7→R8→R9；不得跳到最终打标签。

### 后续1. R5：远程读取统一接入

**对应原卡7A，仅持续运行的本地HTTP模拟器。**

- [x] provider_queries服务作为API和MCP的共同入口。保留ErpClient现有协议，不猜真实ERP地址/字段；只在具备严格映射后移除对应API的remote门禁，不能回退Mongo再标ERP。
- [x] 按既有Part/Supplier/Inventory/Order DTO校验完整必需字段。缺字段返回明确错误，不造0、单位、版本或完整实体。
- [x] 聚合校验page/page_size/pages/total、记录数量、实体ID、重复页/实体；最多100页/10000条，并扣减原调用剩余预算。按原手册保守门槛，缺页、矛盾或达到页数/记录上限时明确不完整，不返回“全量成功”。
- [x] 模拟器测试API/MCP同输入同结果、严格缺字段拒绝、正常两页、重复/越界/total异常/预算耗尽。禁止真实ERP请求；更新README/契约。

实现和本地验证详见[evidence/P09-R5.md](../../evidence/P09-R5.md)。实现提交`d88abd00926943fc28e1f6148b1b85301109b797`已推送且GitHub API核对`origin/main`一致；Actions run `42462367242` 的 `p06-offline` 成功（不是P09 offline门禁）。R5交接文档的独立提交/推送已完成后，方进入R6。

### 后续2. R6：远程一次dispatch与持久对账

**对应原卡7B/7C。需要R5，但真实写capability仍关闭。**

- [x] 为operations新增远程专用一次认领及dispatch方法。内部action包含稳定provider范围+原业务action，沿用owner/action/key唯一约束，不改变本地旧索引。
- [x] provider范围由配置端点规范身份稳定派生（剥离认证/查询片段），不能来自模型或每次随机值。保存原action、provider范围、规范payload hash、审批关联、关联号、dispatch标记、外部结果/ID。
- [x] 复用服务器审批验证：owner/action/payload/版本一致，不能只检查approval_id存在或相信approved=True。审批与operation的一次关联按当前消费规则原子保留。
- [x] 新认领胜者原子写dispatch并获持久确认后才可POST一次。已有operation永不自动再POST，包括lease过期、服务重建和崩溃恢复；同键异payload冲突。
- [x] dispatch后超时、取消、HTTP/JSON损坏、解析失败、进程崩溃、保存结果失败都进入待对账；不靠client内存集合保证幂等。
- [x] reconciliation先分远程，只lookup；普通404、超时或关联不能核实继续unknown。不得因没有本地订单返回retryable。本地事务恢复路径保持原安全语义。
- [x] 真实Mongo+持续HTTP模拟器计数：并发请求POST≤1、丢响应后重建服务lookup同一单仍POST1、dispatch后崩溃恢复不重发、损坏JSON/保存失败unknown、404unknown、owner/provider隔离、异payload冲突。新增跨进程恢复测试，不用单个client计数替身冒充持久性。
- [x] 更新接口/模块README和证据，提交推送。F15/F16仍not_run，不声称ERP联调完成。

### 后续3. R7：补23工具逐项证据

**对应原卡8。**

- [x] 依据P08_REFERENCE_TOOL_NAMES列出原23项（15读、8写）；另有内部工具不能顶替其中任何一项。
- [x] 在真实MCP客户端测试正常及负向业务输入；不存在实体/仓库和非法订单状态由服务端实际返回空结果或明确错误。逐项注册schema另通过实际MCP list_tools核对；历史本地jsonschema非法附加字段断言未冒充本轮HTTP负例。
- [x] 写工具各自测未批准拒绝、批准成功、相同键重放、错误owner拒绝及过期审批版本拒绝；再验证改单/库存旧expected_version失败；复用订单/收货集成测试。
- [x] 每工具记录正常/负向输入、实际MCP结果、具体DB前后事实及测试名；不声称全库相同。
- [x] 23项均有合成local_seed正常业务证据，工具矩阵作为脱敏摘要见[evidence/P09-R7.md](../../evidence/P09-R7.md)。真实ERP F15/F16仍not_run；P09总体门槛继续开放。

### 后续4. R8：双尺寸真实流程与格式打开

**对应原卡9前半。**

- [ ] 两套viewport固定1440×900、390×844，workers=1。每个尺寸独立执行查询→实际报告→真实下载→草稿→编辑数量/金额→刷新待审→重启恢复→批准→重复批准。
- [ ] 下载核字节数、SHA256、解析内容/业务值、来源、owner/run归属；不能route.fulfill伪造成功业务/文件。允许abort/延迟做故障注入。
- [ ] 固定案例55套/660.00元，改60后720.00元；刷新和后端重启后保留最新版本，批准后相同单号/ID、仅一张新增订单与一个成功operation，inbound与流水按实际规则核对。
- [ ] 重启helper必须继承R0两Mongo URI、COMPOSE_FILE、project、数据库、source和model flags；不能重启后读旧数据。
- [ ] 保留既有三图/HTML确认，补MD/CSV/JSON实际打开记录；每截图对应文件名/hash和同批次文件。没有打开能力就not_run，解析不顶替打开。
- [ ] 更新E2E、矩阵与证据，提交推送。F09/F17只按真实覆盖关闭。

### 后续5. R9：完整门禁、CI、干净检出与最终标签

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

### 后续6. 每卡交付与最终完成条件

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
