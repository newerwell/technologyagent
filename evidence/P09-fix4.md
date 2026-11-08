# P09 最终补修证据

status: in_progress
stage: P09
environment: Windows / uv 项目环境 / npm 前端锁文件；本机 Mongo replica set 与 Docker daemon 当前不可用
model_mode: 未运行 live
data_source: 新测试仅用固定时钟与内存合成数据；本机 local_snapshot 未作为采购夹具

## 任务卡 0：必要功能基线

- commit：`b3a0d899d3695f45cba489c8869bd6d0c2576c1c`；推送后 `origin/main` 相同。
- 纳入库存快照适配及API/MCP/本地工具/UI接入、事实与约束处理、配置、对应测试和文档；未纳入 `.env`、原始库存、metadata、运行数据。
- 保留未提交审查文档、截图、`.dsh-meow/`、`frontend/AGENTS.md`。
- `tests/unit/test_inventory_snapshot.py`：3 passed；`tests/unit`：263 passed；前端10个文件/39项 passed；typecheck passed。
- `tests/integration/test_inventory_snapshot_routes.py` 曾因默认Mongo副本集名称与standalone不符失败；用directConnection后连接拒绝，Docker daemon不可用。此项为环境阻断，不记为产品通过。

## 任务卡 1：停用物料预览

反例 RED：`uv run python -m pytest --basetemp .runtime/pytest-task1-red tests/unit/test_replenishment_service.py -q -rs`，2 failed。旧实现将 `active=False` 的P001仍返回 `actionable=True`、quantity=55、total_cents=66000、Q-P001。前端RED也观察到原页面只显示 `part_inactive` 英文标记，未显示用户可读原因。

实现：`ReplenishmentService.preview`对停用物料保留真实 available=15、projected=25、shortage=55、warning=true，并使用 `PreviewLine.model_validate`重建不可采购结果；候选报价/推荐/数量/总额清零并添加`part_inactive`。MCP工具描述和数据页解释“物料已停用”；`DraftService.prepare`既有409拒绝保持不变。

| 检查 | 结果 |
|---|---|
| `uv run python -m pytest --basetemp .runtime/pytest-task1-green2 tests/unit/test_replenishment_service.py tests/unit/test_replenishment.py -q -rs` | 14 passed，exit 0；含停用/启用混合预览及草稿409且预览不运行 |
| `npm --prefix frontend test -- --run src/components/data/ReplenishmentPreview.test.tsx` | 6 passed，exit 0 |
| `uv run python -m pytest --basetemp .runtime/pytest-task1-full-unit tests/unit -q -rs` | 266 passed，exit 0 |
| `npm --prefix frontend run typecheck` | exit 0 |

任务卡1提交：`881ac46de956aff29e428f6d050cfa47d49f308e`；推送后`origin/main`相同。完整P09 offline/browser/live及Mongo集成尚未重跑；不创建`phase-p09`，不表示P09完成。

## 任务卡 2：保留模型修订正文

反例 RED：`uv run python -m pytest --basetemp .runtime/pytest-task2-red tests/unit/test_graph_answer_preservation.py -q -rs`，1 failed。首轮正文缺少报价失效原因，语义评审要求补充；旧执行器在每轮评审前以核验核心文本替换模型回答，导致第二轮模型修订仍被覆盖并最终失败。

实现：核验核心事实只附加到每次模型调用的系统消息副本；`state.messages`、原始请求和模型最终正文保持独立。确定性审查仍先执行，语义审查通过后才发布正文，未引入第二个最终回答字段。

| 检查 | 结果 |
|---|---|
| `uv run python -m pytest --basetemp .runtime/pytest-task2-green tests/unit/test_graph_answer_preservation.py -q -rs` | 1 passed，exit 0 |
| `uv run python -m pytest --basetemp .runtime/pytest-task2-unit tests/unit/test_graph_answer_preservation.py tests/unit/test_verified_answers.py tests/unit/test_deterministic_review.py tests/unit/test_fact_checks.py -q -rs` | 28 passed，exit 0 |

任务卡2源码提交：`16c4c3afae25815477a3fabfcdd90a7028038355`；push后远端SHA相同。P09完整offline/browser/live门禁及真实模型批次均未在本卡执行。

## 任务卡 3：提交事实快照与订单说明覆盖

### 反例与修复

- RED：订单说明只含 `PO-1`、没有数量或总额时，旧 `_order_answer_fact_check` 会通过。新增反例要求单号存在时仍必须覆盖每条已知数量和订单总额。
- RED：订单仓储此前不接受 `verification_facts`（`TypeError: unexpected keyword argument`）；新仓储测试确认该事实要随订单插入保存。
- RED：语义评审此前会丢弃订单的提交事实快照；回归扩展后因 `verification_facts` 不在白名单而 `KeyError`。
- RED：正确的“报价交期不代表已经到货”措辞被词面规则误判为实际到货；新增否定上下文测试复现。
- 修复：批准事务从同一事务读取的启用物料、有效报价和 run 的已保存订单意图构造订单事实快照，并与订单、inbound、审批消费、operation结果原子提交。保存数量/单位/仓库、quote/supplier、报价交期和观察时间、最大交期约束；没有单位时不从当前目录补写。
- 修复：结算只读取成功 operation、持久订单、已消费审批和提交快照；不再查询当前目录补单位。普通订单接口剥离内部快照；语义评审只收到快照白名单字段。
- 修复：正文硬门槛要求单号、每项数量、订单总额；有保存的用户交期时要求覆盖用户约束和批准报价交期，并拦截没有收货事实支撑的肯定收货陈述。明确否定的“不代表已经到货”可通过。两次纯正文修订仍不会调用订单写服务。

### 实际检查

| 检查 | 结果 |
|---|---|
| `uv run python -m pytest tests/unit/test_order_review_bounds.py tests/unit/test_semantic_review.py tests/unit/test_order_verification_persistence.py -q -rs` | 13 passed，exit 0 |
| `uv run python -m pytest --basetemp .runtime/pytest-task3-unit tests/unit -q -rs` | 270 passed，exit 0 |
| `uv run python -m pytest tests/integration/test_order_review_loop.py -q -rs` | 3 errors，exit 1；测试夹具连到 `127.0.0.1:27027` 的 Mongo standalone，但要求副本集 `ta-rs`。未执行集成体，故不记为通过；Docker daemon仍不可用。 |
| `uv run ruff check`（本任务触及文件） | exit 1，报告26项，含多个原有导入/异常处理/格式问题；本任务未把既有 lint 问题当作验收通过。 |
| 真实模型/live、P09 offline/browser | 本卡未运行；Mongo副本集不可用，且完整批次不属于本任务的定向门禁。 |

新增 Mongo 集成断言保留 55 套、66000分、最大交期7天、批准报价交期5天及报价/供应商ID，并要求只写一张订单、一个成功operation，inbound 10→65、on_hand保持20。由于 Mongo 服务环境阻断，本轮这些事务事实没有被实际执行核验，状态为待补验。

提交：`d7a4907714b0dde01cf9ddc0afaeab37604f6c75`，已推送；`git ls-remote origin refs/heads/main`核对为同一SHA。交付记录提交`bfe03f4e0d7f5ae2994ac3144e4668a90a243e9f`远端一致；GitHub Actions run [40676320946](https://github.com/newerwell/technologyagent/actions/runs/40676320946) 的`p06-offline`在本次检查时仍`in_progress`，不是P09专属门禁。本任务不创建或移动 `phase-p09`。

## 2026-11-08 剩余工作复核后的任务卡 3 定向补修

来源：[2026-11-08-P09-remaining-work.md](../docs/reviews/2026-11-08-P09-remaining-work.md)。本次只按复核优先级补订单说明/收货边界；task1缺库存原因及task4–11尚未开始。

- RED：`test_order_answer_rejects_completed_receipt_without_receipt_fact` 在旧规则下通过错误正文“订单已完成收货”，定向测试实际失败（期望拒绝，旧行为通过）。
- GREEN：收货硬校验覆盖已收货、签收、入库、完成收货、收货完成、实际到货等肯定描述；明确否定上下文保留可通过。
- RED evidence：复审保存的合成 probe 已用模型关闭、内存持久订单/成功operation/已消费审批调用 `_settle_protected`，结果为 failed / POST_COMMIT_REVIEW_FAILED / committed_facts=true；根因是fake mode无模型，初始summary仅有单号/计数，正文硬检失败后修订断言要求模型。
- GREEN：新增真实 `_settle` 单测，fake无模型时按持久订单与verification_facts生成完整初稿，并走原数量/单位/金额/交期/收货硬检查。验证返回summary包含PO-1、55套、66000分、用户7天要求、批准报价5天及“报价交期不代表已经到货”。缺单位/交期的历史订单显示未知，不查当前目录补造。
- `tests/unit/test_order_review_bounds.py`、`tests/unit/test_semantic_review.py`、`tests/unit/test_order_verification_persistence.py`：16 passed，exit 0；完整`tests/unit`：274 passed，exit 0。
- `tests/integration/test_order_review_loop.py tests/integration/test_order_settlement_failures.py`：8 errors，exit 1；全部发生于测试夹具 ping，27027节点声明无副本集名称，测试要求`ta-rs`，测试体未运行。当前`mongo-data`目录包含持久Mongo数据，未使用或重置；Docker daemon管道不存在。故真实Mongo事务/业务集合单数断言仍not_run。
- 本轮本地HEAD起点43bf999；代码提交`8135398fbc6cf293dca4efdb50bfdfc880f46d57`及证据交接提交`4e6860de8d999f26e204fba9cf55240362e308c2`均已推送。远端`origin/main`核对为4e6860de；旧标签未修改。GitHub Actions run 42436925144当时`in_progress`，不是P09专属验收。

任务卡3目前状态：确定性fake结算和正文反例已关闭；Mongo真实事务集成仍开放。按实施手册要求不推进task1、task4或最终验收，不创建`phase-p09`。

## 2026-11-08 R0：隔离副本集与提交后订单结算补验

### 环境隔离与启动配置

- 新增`compose.p09-acceptance.yaml`：独立Compose project/container，Mongo 8.0、`ta-rs`、仅`127.0.0.1:27028`，`/data/db`绑定新卷`technologyagent-p09-acceptance-mongo`。实际`docker compose config` exit 0；inspect确认端口与命名卷。现有`technologyagent-mongodb`继续使用原`mongo-data`，未读写或重置。
- 容器health为healthy；`rs.status()`确认`set=ta-rs`、`myState=1`、成员`localhost:27028`。初次`hello`在副本集初始化前为非primary，初始化后为PRIMARY。`scripts.init_db`在固定库`technologyagent_test_p09_verify`成功，报告`replicaSet=ta-rs primary=True`。
- 新增`scripts/p09_acceptance_env.ps1`，按offline/browser/live设置固定test库、两条Mongo URI、Compose路径/project、local_seed及模型开关；在当前PowerShell进程内保存原env（包括缺失与空值状态），模式切换不覆盖原快照，`-Restore`恢复且不写盘/输出密钥。启动脚本在隔离Compose模式下、建立runtime/启动容器前拒绝非`technologyagent_test_*`库和错误URI。
- RED：`test_dotenv_does_not_replace_explicit_empty_environment_value`使用合成`.env`复现旧逻辑将显式空值回填为`from-file`；修复后只对缺失变量导入。另新增模式/继承/恢复、未知模式拒绝、start非test库前置拒绝用例。

### 订单结算反例与真实Mongo回归

- 首次在真实隔离副本集执行三个集成文件：`6 failed, 3 passed`。排查表明订单实现已按确定性事实优先：旧测试期望在两类检查各需修订时只计1次；错误事实替身将最终正确答案的首次语义评审设为失败但只剩一次修订；provider异常用例注入没有`stream`的`object()`，导致在语义评审前的正文硬检查修订阶段先触发`AttributeError`。以上是回归替身与当前两次修订契约不一致，非DB事务事实失败。
- 修正测试夹具以表达实际契约：提交后最多2次正文修订/3次检查；只在确定性事实检查通过后触发语义检查；provider异常前用来自持久核验事实的完整正文通过确定性门槛。错误数量/金额反例仍保留第一版错误值，并断言数据库最后只有正确数量/金额且无重复订单。
- GREEN：`tests/integration/test_order_review_loop.py tests/integration/test_order_settlement_failures.py tests/integration/test_inventory_snapshot_routes.py`，真实Mongo副本集`9 passed`，exit 0。数据库断言确认新增一单/一个成功`order_create` operation；批准消耗一次；`P001/W01`为55套/66000分，`I001 inbound 10→65`、`on_hand=20`；保存用户7天、批准报价5天/ID/供应商/观察时间。修订耗尽和provider异常只写失败终态并携已提交事实，不再次批准或提交。
- `tests/unit/test_start_dotenv.py tests/unit/test_p09_acceptance_environment.py`：4 passed，exit 0。完整R0三集成文件最终复跑如上9 passed。
- 最终合并定向复核：`tests/unit/test_start_dotenv.py tests/unit/test_p09_acceptance_environment.py tests/unit/test_order_review_bounds.py tests/unit/test_order_verification_persistence.py tests/unit/test_semantic_review.py tests/integration/test_order_review_loop.py tests/integration/test_order_settlement_failures.py tests/integration/test_inventory_snapshot_routes.py`：30 passed，exit 0。
- 初始尝试`uv run`在初始化用户级uv缓存时因ACL拒绝，未启动pytest；随后使用仓库`.venv`实际执行。运行时pytest cache目录也有ACL warning，因此定向命令使用`-p no:cacheprovider`和项目独立`--basetemp`。

R0验收已完成，当前接续R1“停用物料且缺库存时同时保留inventory/part_inactive标记”。完整P09 offline/browser/live、真实模型固定批次、最终矩阵、CI专属门禁与干净检出尚未执行；不创建`phase-p09`或将P09标记完成。旧测试首次失败与历史证据保留。

R0实现提交`098d038d6d71d661dde8aded77d48b257aa21bb1`及证据/交接提交`3949bc95b5146fcae87b76a4c418e14511477cda`已推送；最新`HEAD`与`git ls-remote origin refs/heads/main`一致为`3949bc95b5146fcae87b76a4c418e14511477cda`。提交后CI状态尚未能读取：本机无`gh` CLI，GitHub MCP查询遇到传输错误；不能将CI记为通过。当前旧阶段标签保持不动。

## 2026-11-08 R1：缺库存停用物料标记

- RED：`tests/unit/test_replenishment_service.py::test_inactive_part_without_inventory_reports_both_reasons`在旧实现失败；实际`missing_fields={'inventory'}`，预期还要有`part_inactive`。
- 修复：只在库存缺失分支增加停用原因；没有改`available/projected/shortage/warning`或构造库存/报价。含库存时已有停用逻辑仍保留真实15/25/55与`part_inactive`，报价候选和可采购数量清空。
- 后端：`tests/unit/test_replenishment_service.py tests/unit/test_replenishment.py`，15 passed，exit 0；含启用恢复推荐、混合批次、停用草稿409拒绝。
- 浏览器组件：`npm --prefix frontend test -- --run src/components/data/ReplenishmentPreview.test.tsx`，6 passed，exit 0，确认中文“物料已停用”。沙箱内首次执行因esbuild读取Windows父目录ACL失败，获批后相同命令重跑成功。
- R1代码/evidence提交`40fac204c6c6d681d51f5e25f38c90e47197a179`已推送，push成功；推送当时`git rev-parse HEAD`与`git ls-remote origin refs/heads/main`均为该SHA。R2以后尚未开始。CI仍未能读取，不能记为passed。

## 2026-11-08 R2：统一模型调用、预算与有限重试

- RED：先增加`collect_model_response`反例：首delta前`RemoteProtocolError`后成功必须是2次请求/2次run预算收费/两组唯一start-finish，且失败响应不进入成功deltas；任一token、tool_call或usage后断流不得重试；HTTP/provider协议错误即使`retryable=True`也不得重试；预算拒绝或取消后不得发起第二次。旧代码因collector不存在，2项旧观察测试通过、6项新测试按“collector不存在/首次失败异常”失败。另为`semantic_review(emit=None)`增加传输失败重试回归，旧直连路径在首个MODEL_UNAVAILABLE处失败。
- 总期限竞态回归以可控时钟复现：第二次模型流在逻辑deadline之后完成，旧实现仍返回成功（pytest明确`DID NOT RAISE ModelProviderError`）。修复后统一收集器在流完成后再核对期限，超时attempt按错误结算，不返回迟到正文。
- 实现：增加`ObservedModelResponse`与`collect_model_response`；每次真实请求先检查取消/活跃期限、计一次模型预算、发唯一start，再请求并发唯一finish。总期限只初始化一次，最多重试一次，限定为首delta之前传输错误/超时。ModelProviderError只按`MODEL_TIMEOUT`/`MODEL_UNAVAILABLE`分类，不依赖retryable标志；收到任意delta后不重试。取消/期限等待期间轮询并取消、await未完成流。usage仅保留安全token数值；缺失时为None。主图工具parent id绑定成功尝试call id。
- 四个入口已切换：Graph主模型、语义评审（含`emit=None`）、订单意图抽取、订单说明修订。后者继续只消费正文/拒绝tool_call，不重新提交订单。
- 定向unit：模型观察、语义评审、订单意图与订单正文修订`38 passed`（新增修订入口回归后）；最终完整`tests/unit`为`292 passed`，exit 0。最终受影响集成`tests/integration/test_agent_tools.py tests/integration/test_agent_stream.py`为`14 passed`，exit 0。Graph重试回归核对1次工具调用、失败/成功模型事件各一对、预算/模型请求数同为4，工具`parent_call_id`指向成功尝试。
- Ruff命令未运行：`.venv`没有ruff模块（`No module named ruff`，exit 1）；不报告为lint通过。真实模型、完整P09 offline/browser/live未运行；R3尚未开始。CI待推送后查询。
- R2代码提交`b8cf2c4cb0db00cd6502ed257b02783b2aa4107b`已推送，随后核对`git rev-parse HEAD`与`git ls-remote origin refs/heads/main`均为该SHA。Actions run `42444632271`（代码提交）和`42444744927`（本轮证据提交）均结论`failure`；job `p06-offline`在启动Mongo容器时退出，日志明确报告GitHub runner Linux kernel 6.19 与当前Mongo镜像不兼容，pytest未开始。该环境故障不能记为CI通过，也不能归因于R2代码测试。run链接：[代码push CI](https://github.com/newerwell/technologyagent/actions/runs/42444632271)、[证据push CI](https://github.com/newerwell/technologyagent/actions/runs/42444744927)。旧阶段标签不动，不创建`phase-p09`。

## 2026-11-08 R3：MCP快照、结构化报告范围与来源

- RED：新增实际MCP业务入口无可证明完整页集时必须失败的测试。旧`_business_call`把`local_seed`库存页直接返回成功但没有`snapshot_id`；本轮改为执行分页快照校验，无法绑定时返回`INCOMPLETE_SNAPSHOT`。MCP子进程测试固定四个业务来源为`local_seed`并清空快照路径，实际注册工具`inventory_page`与`inventory_warning`返回快照标识。
- RED：范围回归先失败：约束无`all_warehouses`/`warehouse_names`；报告选择器把结构化范围字典当原始字符串解析并抛`TypeError`。现由请求解析、参数约束、报告dataset选择和最终范围核验共用结构化scope。全仓明确覆盖但不删除持久W01偏好；工具移除单仓参数。全仓拒绝W01筛选数据集，完整无仓过滤页集包含来源内全部仓位；`A区-1号库`按真实来源名称精确匹配；`物料编号72`维持原ID，不补`P`前缀；请求单物料而页集出现额外物料时拒绝。
- 真实报告回归使用完整全仓授权页集调用`artifact_report(md)`，重新打开已登记文件，核对正文含两个来源仓位且`verify_report_artifact`成功。正式报告检查同一结构化scope；服务端内容/范围/来源/哈希核验仍是生成`report_verified`前置条件。
- 快照拒绝路径：报价与补货仍返回`UNSUPPORTED_OPERATION`；HTTP错误metadata和本地/MCP工具错误metadata保留`local_snapshot`、原`as_of`与完整性，不改供应商Provider的`local_seed`配置。原始快照文件字节不变。
- 失败轨迹：范围反例首轮5项失败，暴露旧字段缺失与字符串/字典接口不匹配。修复迭代中出现并修复`GraphExecutor`的旧形参名引用错误；快照HTTP断言初次揭示全局错误metadata来源为`none`；最终正文回读反例初次揭示合成库存行缺少报告要求的数值字段；新增供应商读取断言首次触发未连接Mongo的测试夹具错误，随后改为只读校验Provider配置，未调用该数据源。按来源模型补足有限数值后，报告生成/文件重开/正文范围核验通过。最终命令及结果：

```powershell
$env:MONGODB_DATABASE='technologyagent_test_p09_verify'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .runtime/pytest-R3-final3 `
  tests/unit/test_p06_request_constraints.py `
  tests/unit/test_p07_specialists_skills.py `
  tests/unit/test_required_report.py `
  tests/unit/test_mcp_inventory_snapshot_fail_closed.py `
  tests/integration/test_analysis_artifact_flow.py `
  tests/integration/test_inventory_snapshot_routes.py `
  tests/integration/test_mcp_tools.py::test_mcp_keeps_legacy_tools_and_registers_all_p08_names -q -rs
# exit 0: 63 passed
```

- P09完整offline/browser/live、固定真实模型批次、人工文件打开及P09专属CI尚未执行；本卡不补记这些验收。R4–R9仍开放，真实ERP F15/F16仍`not_run`。旧标签不动，不创建`phase-p09`，不开始P10。
