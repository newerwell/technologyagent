# P09 最终补修交接

## 2026-11-08 新计划 A4 实施中

- A4 runner/healthcheck实现和本地验证已完成；`evidence/P09-A4.md`记录了RED/GREEN、Compose解析和现存隔离Mongo的只读探针。当前工作区有A4待交付修改，未暂存；推送后的GitHub Actions run尚未核实。
- A4定向10 passed、完整unit 336 passed，Compose两配置解析 exit 0；错误set与非PRIMARY负向探针各exit 1。没有重启/重建隔离Mongo。
- 下一步：检查diff和文件范围，提交A4实现/文档；push后确认origin/main和本次Actions的Linux kernel、Mongo PRIMARY/事务、依赖、pytest步骤实际结果。CI通过后再进入R5；若未通过，保持A4开放并修复该卡。
- 保留未跟踪审查文件、`.dsh-meow/`、`evidence/screenshots/`及`frontend/AGENTS.md`，不暂存；不创建phase-p09，不开始P10。

> **最新进度（A1–A3已推送）：**A3在隔离Mongo副本集验证v2实际演化期间v1旧审批恢复/重放、单一订单/operation、库存值和旧checkpoint全量文档不变；33项指定回归通过。提交`91a661d04a3767dca1f4fe6019ab0fa44390c906`与origin/main一致；GitHub没有返回关联CI状态或run。下一卡A4兼容runner/CI，R5–R9未完成；不打phase-p09、不开始P10。历史报告保留当时语境。

> **后续环境更新：**用户启动Docker后，控制接口已恢复，Docker29.9.2；独立容器healthy，27028 hello为ta-rs PRIMARY，命名数据卷核对正确。无需重建实例；按新计划A1继续产品补修。此前Docker不可连接是历史检查结果，CI兼容问题仍独立开放。

stage: P09-final-closure
current_task: A3已推送；下一卡A4 CI环境
base_head: 91a661d04a3767dca1f4fe6019ab0fa44390c906
base_origin_main: 91a661d04a3767dca1f4fe6019ab0fa44390c906
working_tree: A3已交付；本次仅提交远端CI状态补记；.dsh-meow、截图、frontend/AGENTS及其他未跟踪复审文件保持未暂存
previous_phase_tag: 不移动任何旧标签；不创建phase-p09

## 2026-11-08 新计划A1进度

- RED：旧实现对HTTP 401/429/500错误体ReadTimeout错误地归类`MODEL_TIMEOUT`；HTTP 200坏gzip归类可重试`MODEL_UNAVAILABLE`；HTTP 500坏gzip覆盖状态；timeout_seconds=120时61秒迟到成功。定向反例旧版5项失败；60秒单测明确`DID NOT RAISE`。
- GREEN：known non-2xx不读取/回传错误正文并保留HTTP分类；成功响应DecodingError映射不可重试`MODEL_PROTOCOL_ERROR`；逻辑期限`min(60, caller timeout, run剩余)`且重试不刷新。受影响unit 47 passed，完整unit 312 passed。
- 命令及证据见`evidence/P09-A1.md`。这只关闭A1；下一卡A2。完整P09门禁尚未执行，A3/A4及R5–R9保持开放。

## R2 已验证

- Graph主模型、语义评审（包含`emit=None`）、订单意图抽取、订单正文修订均使用统一模型收集器。
- 每个传输重试单独收费/记录，最多额外一次且仅限首delta前；总期限不重置；取消和期限触发会清理模型流。主图工具parent指向成功模型尝试。已提交订单说明修订不触发业务写。
- 可控时钟测试曾复现“deadline后完成仍成功”；修复后定向观察测试12 passed。完整unit 292 passed，exit 0；`test_agent_tools.py`与`test_agent_stream.py`集成14 passed，exit 0。
- Ruff未运行：仓库`.venv`缺模块；真实模型及完整P09 offline/browser/live尚未运行。R2代码提交`b8cf2c4cb0db00cd6502ed257b02783b2aa4107b`已推送并核对`origin/main`一致；Actions runs `42444632271`和`42444744927`均在Mongo容器启动前失败，runner Linux kernel 6.19与当前Mongo镜像不兼容，pytest未开始。CI不记通过。R3未开始。
- 下一卡R3：真实注册MCP入口的快照标识、结构化报告scope及快照错误来源；不得提前开始R4。

## 本卡已完成

- 订单写事务内持久化来自服务端核验记录的`verification_facts`，常规订单API剥离此内部字段。
- 结算以提交时快照检查正文数量、金额、单号、已保存交期约束与报价交期；不向当前目录回查历史单位；没有收货事实时拒绝肯定收货语句。
- 语义评审只获必要白名单字段；正文可修订两次但不能重放提交。
- 定向单元回归13 passed；完整unit 270 passed。
- 任务卡3提交`d7a4907714b0dde01cf9ddc0afaeab37604f6c75`已推送，`origin/main`一致；交付记录提交为`bfe03f4e0d7f5ae2994ac3144e4668a90a243e9f`。GitHub Actions run 40676320946 的`p06-offline`仍运行中，且不是P09专属门禁。
- Mongo集成无法执行测试体：本地27027是standalone，测试要求`ta-rs`副本集；Docker daemon不可用。证据见`evidence/P09-fix4.md`。

## 仍未完成

- 本卡Mongo集成回归尚未通过/运行；P09完整offline/browser/live和真实模型批次尚未运行。
- 任务卡4–11未执行；本地最终矩阵尚未关闭。
- 不创建`phase-p09`，不开始P10。

last_command: `uv run python -m pytest --basetemp .runtime/pytest-task3-unit tests/unit -q -rs`
last_exit_code: 0
last_error: `tests/integration/test_order_review_loop.py` requires local Mongo replica set `ta-rs`; current endpoint identifies as standalone.

## 2026-11-08 R3续验

- 实际MCP注册路径`_business_call -> dispatch_business`已绑定local_seed库存/预警页的完整集合snapshot_id；无完整快照时失败关闭。MCP subprocess integration强制local_seed和空快照路径，减少本机`.env`对合成验收源的影响。
- 请求解析新增`all_warehouses`、`all_inventory`、仓位真实名称和显式原始物料编号；显式全仓覆盖当前轮默认W01，不删除持久偏好。报告选择、文件生成前范围过滤、最终`report_verified`核验统一使用同一结构化约束。完整跨仓报告实测重新打开，正文含全部两个测试仓位并通过服务端核验。
- snapshot报价/补货仍拒绝，HTTP/MCP/local工具错误保留快照来源、采集时间和完整性metadata；供应商Provider保持local_seed。
- RED定向用例先失败5项；实现中曾发现并修复report picker旧变量名引用；随后63项最终定向回归通过，exit 0。具体命令、首次失败及限制见`evidence/P09-fix4.md`。
- 当前R3改动尚待提交/推送与远端SHA/CI确认。完整offline/browser/live、固定live批次、人工打开和R4–R9未运行。保持旧标签、不创建`phase-p09`、不开始P10。

## 2026-11-08 任务卡3续验

本地复核后再次补了fake结算初稿和肯定收货边界。新增真实`_settle`单测及正文回归通过，完整unit 274 passed。Mongo事务集成8项未进入测试体：本机27027是standalone，测试要求ta-rs副本集；现有mongo-data含持久数据且Docker daemon不可用，未修改该目录。当前任务卡3仍因真实Mongo事务证据缺失而部分开放；按一次一张卡规则不继续task1/4。

任务卡3代码提交：`8135398fbc6cf293dca4efdb50bfdfc880f46d57`；证据/交接提交：`4e6860de8d999f26e204fba9cf55240362e308c2`。均已推送，`origin/main`核对为4e6860de。当前CI run 42436925144检查时仍运行中。旧标签未移动，`phase-p09`不创建。

## 2026-11-08 R0续验

- Docker版本29.9.2；只读确认27028原先没有监听者、专用容器/卷不存在。按`P09-remaining-implementation.md`新建并启动隔离实例，没有碰原`mongo-data`。
- 新副本集`ta-rs`为PRIMARY；`technologyagent-p09-acceptance-mongo`挂载`/data/db`，端口只映射`127.0.0.1:27028`。隔离helper模式切换/子进程继承/恢复、显式空env、非test数据库启动拒绝共4项通过。
- R0三份真实Mongo集成：首次6失败/3通过，归因于旧测试替身没有遵守“确定性检查通过才语义检查”以及两次修订契约；更新测试后9通过。严格事实断言保留并执行：55套、66000分、I001 inbound10→65、on_hand20、用户7天/报价5天、单一订单/operation。
- R0实现提交`098d038d6d71d661dde8aded77d48b257aa21bb1`和证据/交接提交`3949bc95b5146fcae87b76a4c418e14511477cda`均已推送；后者为当前`HEAD`且`origin/main`相同。GitHub CI未能查询：没有`gh` CLI，GitHub MCP传输失败，不记为通过。`uv run`缓存ACL限制，定向Python通过仓库`.venv`运行。
- 下一步R1先确认缺库存停用物料反例和差异，再修复测试；本任务完成前不推进R1。

## 2026-11-08 R1续验

- 先复现缺库存停用物料遗漏标记：旧实现仅有`inventory`，新增定向测试失败；修后`inventory`与`part_inactive`同时出现，行动/数量/金额/报价继续关闭。
- 后端定向15 passed，前端`ReplenishmentPreview` 6 passed；组件显示“物料已停用”。未修改共享合同或库存事实。
- R1实现/evidence提交`40fac204c6c6d681d51f5e25f38c90e47197a179`已推送，推送时远端main同SHA；CI状态仍无法查询，不作通过声明。下一卡R2。

## 2026-11-08 R4实施续接

- 当前卡：P09剩余实施R4“冻结v1并接入真正的版本路由”。本轮已拆分主图/订单图v1与v2实现，并接入GraphExecutor、OrderWorkflowService版本路由；工作区证据见`evidence/P09-R4.md`。
- 确定性版本隔离单测30 passed，compileall exit 0。旧fixture字节未变，SHA-256固定为`1fd530124549641fd790a9e8a730db51e2c2b14dab6aa894f501e1dbb950a318`。
- 真实Mongo升级恢复集成尚未进入测试体：27028是standalone而非`ta-rs`，Docker daemon不可用。不要复用27027或日常`mongo-data`，也不要更改此失败为passed。
- 部分实现提交`55eb63d0b5acaf403968c076951864a5d7a13ca5`已推送，远端main SHA一致。Actions run `42448456550`因Mongo镜像在GitHub Linux kernel 6.19+启动失败，健康检查失败且pytest跳过；不作为通过。
- R4未关闭前不开始R5。后续先恢复本机隔离`technologyagent_test_*`的ta-rs副本集，并解决/替换CI Mongo镜像兼容性后运行`tests/integration/test_graph_upgrade.py`，核实旧审批恢复仅一单及新v2 namespace隔离；随后定向复跑并补交证据。

## 2026-11-08 A4续接

- Actions `42454755841`已通过Ubuntu kernel guard、Mongo健康检查/init和依赖安装，pytest失败于历史fixture字节SHA与答案事实回归；修复后留待新CI核验。
- 最终P03 claim校验现位于回答token发布前；供应商推荐的预览数量/总额证据绑定实际选中的报价/供应商；`总额`和`行金额`按字段分别校验。相关定向回归42 passed，完整unit 341 passed。
- 全integration本机运行219 passed、5 skipped、1环境失败：P00真实Next边界测试与既有dev锁冲突；Docker项目测试未运行。P06完整offline manifest因当前Docker API pipe拒绝访问无法完成，CI才可覆盖Docker沙箱项目。详见`evidence/P09-A4.md`。
- 修复提交`572e0dc73227b3ece1ebdd521862723931f5fab9`已推送且`origin/main`一致。Actions run `42459598060`全绿，P06 offline manifest与Docker沙箱构建均通过；artifact `13608887309`。A4关闭，详见`evidence/P09-A4.md`。可以按实施手册进入下一卡；P09最终矩阵仍未关闭，不创建`phase-p09`，不开始P10。

## 2026-11-08 R5续接

- R5统一远程只读查询已在工作区实现：`ProviderQueries`供REST/MCP共享；映射后按现有Part/Supplier/Inventory/Order DTO校验，完整聚合分页并验证total、页码、记录数和跨页实体ID。超限或缺字段失败关闭，不从Mongo回退。远程写仍关闭。
- RED：新定向用例在实现前于`provider_queries`模块导入处失败；新增订单DTO正例进一步发现嵌套`missing_fields`泄漏，修复后本地回环HTTP模拟器API/MCP相同查询及缺字段拒绝通过。实际结果32定向通过、354完整unit通过；详见`evidence/P09-R5.md`。
- 下一步仅为R5交付：审阅diff、显式stage R5源码/测试/README/evidence/status/本计划，commit/push并核对origin SHA与Actions；推送和CI核对成功后才进入R6。
- 真实ERP与P09完整offline/browser/live、F15/F16均未运行；旧标签不动，不创建phase-p09，不开始P10。无关untracked审查文档、截图、`.dsh-meow/`及`frontend/AGENTS.md`保留未暂存。

## 2026-11-08 R5交付关闭 / R6续接

- R5实现提交`d88abd00926943fc28e1f6148b1b85301109b797`已推送，GitHub API返回的`origin/main`相同。关联Actions run `42462367242`成功：实际job为`p06-offline`，并非P09 offline；P09 offline/browser/live仍未运行。
- R5本地定向32 passed、完整unit 354 passed；证据`evidence/P09-R5.md`。R5不包含真实ERP或远程写，F15/F16继续not_run。
- 当前开始R6，范围限远程写一次性dispatch持久屏障和只读对账；使用本地HTTP模拟器与`technologyagent_test_*`隔离Mongo，真实ERP写保持关闭。先添加跨进程/重启反例并核对当前OperationRepository和ReconciliationService，再实施。
- 未跟踪的审查文档、截图、`.dsh-meow/`及`frontend/AGENTS.md`保留不动；不创建或移动`phase-p09`，不开始P10。

## 2026-11-08 R6 交付关闭 / R7续接

- R6提交`939f4a3d58d37891a592dc2aa46eb8cdebc76e94`已push，GitHub API核对`origin/main`同SHA；Actions run `42465776140`成功，job为`p06-offline`，不能当作P09 offline验收。R6 loopback+隔离Mongo 12 passed；完整unit 355 passed；R6/P08集成组合42 passed；compileall、diff-check exit 0。Ruff未安装/未列入锁定依赖，未运行。完整证据见`evidence/P09-R6.md`。
- 下一步进入R7，逐项补23项MCP工具实际结果与数据库证据。真实ERP F15/F16、P09最终offline/browser/live和其他矩阵仍开放；不创建`phase-p09`，不开始P10。
- 全部既有未跟踪审查文档、截图、`.dsh-meow/`和`frontend/AGENTS.md`继续保留。
