# P06-fix2：字段绑定与 P03 固定验收

日期：2026-10-25。实施范围仅为 P06-fix2 与其要求的 P03 前置补验收，不开始 P07。旧 `phase-p04`、`phase-p05` 标签未移动；`.env.example`、`.dsh-meow/`、`frontend/AGENTS.md` 保持原样且未提交。真实调用使用隔离库 `technologyagent_test_p06_fix2_p03live`，没有订单写工具调用。

## 逐任务实现

| 任务 | 实现与确定性覆盖 | 本地提交 |
|---|---|---|
| Task 1：反例基线 | 先添加字段错配/同值跨范围等失败断言，再实现修复；覆盖单价、行额、订单额、数量、交期、布尔业务状态、非有限数值、来源和同范围歧义。 | `abb1727` |
| Task 2：共用字段事实校验 | 新增 `agent/fact_checks.py`，以字段、单位、实体、查询来源与时间绑定主张；金额由 Decimal 精确转分，整数数量/天数拒绝小数；订单持久事实通过适配器进入同一校验。 | `39df739` |
| Task 3：P03约束与多实体回答 | 原请求仓库/物料/交期上限作为 request constraints 保存；安全预警不代替目标缺口；7天请求要求匹配参数的服务端 `replenishment_preview`；完整范围事实缺失、冲突或不唯一时拒绝生成核心结论。对完整同范围服务事实渲染答案核心，带来源、观察时间和筛选条件；有效状态按布尔类型核对。 | `62024e7`、`1db3af3`、`931575f`、`670413d`、`2a8a665`、`8b2d68d` |
| Task 4：独立验收 | Live oracle 独立检查真实模式、成功终态、完整只读查询、原始筛选、答案覆盖及数据库快照；持久运行和事件终态分别对照；无有效报价必须证实完整 P003 报价集且结论相符，截断/不可解析结果计证据不足；受控测试中的 skip 不再算通过。 | `e2f9a1c`、`2a8a665` |
| Task 5：分层验收 | Windows离线、Chromium browser，以及真实模型固定三题各三次分别执行；本节记录实际批次、失败分类和数据库对照。Windows临时目录权限问题由验证脚本使用仓库内隔离 basetemp。 | `746bb8a`及上述测试提交 |
| Task 6：证据与交付 | 更新本证据、P03/P06规格与实施计划、STATUS和 agent README；实现提交已逐任务推送，CI与远程SHA已核对；本次收尾文档提交随后核对。 | 代码/测试提交已推送；最终文档提交待推送 |

主要回归文件：`tests/unit/test_fact_checks.py`、`tests/unit/test_live_acceptance.py`、`tests/integration/test_readonly_scope_answers.py`、现有订单/正文校验测试。修复后的针对性子集 **49 passed**；`tests/unit/test_plan_updates.py` **10 passed**。原始错误用例曾分别复现：持久订单总额/单价互换被放行；库存查询带否定的供应商建议仍被错误分类；用安全预警子集回答目标缺口；仅查报价却删掉7天请求；把失效报价布尔状态当数值或错误接受相反结论；答案省略必要来源/范围或持久事实不一致。修复后这些断言纳入离线全量回归。

### 失败轨迹中的数字归类

从原始 `evidence/P03-A06-live-traces.json` 与本轮失败批次核对后，数字不能脱离字段和范围解释：`2` 在W01预警集合中是服务统计的预警记录数，不是目标缺口件数；`36` 是P003/W01目标库存缺口；`7` 是用户请求的 `max_lead_days`，需要由预览查询参数证明，不表示供应商交期恰为7天；`10` 在W01目标缺口问题中是P004缺口件数，但在报价记录中也可能是最小起订量；`12` 是Q01/S01的单价（1200分），不是订单总额；`1` 可能是P003报价记录数，也可能是报价最小起订量，不能据此说有一条有效报价；`500` 没有作为独立金额主张出现，相关轨迹中的 `60500` 是Q02/S02的行金额分值，不能截成“500”或借给单价字段。上下文不唯一时校验拒绝歧义，不猜数字含义。

## Windows offline 与 browser

- 离线命令：`$env:MODEL_MODE='fake'; $env:RUN_LIVE_MODEL='0'; $env:MONGODB_DATABASE='technologyagent_test_p06_fix2_offline'; uv run python -m scripts.verify_stage P06 --mode offline --report .runtime/reports/P06-fix2-offline-final.json`
- 最终结果：exit 0，**9/9 checks**，157 unit、160 integration、38 frontend tests；Mongo init、真实 Docker sandbox image build、seed、前端 typecheck/build 与 contract check 均通过。报告记录总时长 349.26 秒。
- 首轮全量回归保留失败报告：156 unit 中 1 项失败。`classify_task` 的负向请求处理与 `extract_request_constraints` 不一致，导致“查询库存，不要给供应商和报价建议”被分为 supplier。增加确定性回归后，两者共享否定过滤，单测 10/10 通过；随后最终全量回归通过。该失败未通过放宽测试处理。
- Browser：fake 隔离服务 `technologyagent_test_p06_browser`；`uv run python -m scripts.verify_stage P06 --mode browser --report .runtime/reports/P06-fix2-browser-final.json`，exit 0，manifest 2/2，Playwright **9/9** 通过。
- Browser E2E 使用已登录本地应用与受控 artifact-history 路由验证页面/跨轮历史。它没有验证本轮 Agent 生成的正式文件通过真实后端授权下载链路；此项仍单列未验。用户已确认 `quote-comparison.html` 显示正常，本轮没有重复要求用户检查。

## P03真实模型固定3×3

- 环境预检确认本机真实模型配置字段存在；密钥值未读取到输出、未写入证据。显式启用 `RUN_LIVE_MODEL=1`，运行库为固定 seed 的 `technologyagent_test_p06_fix2_p03live`。
- 命令：`uv run python -m pytest tests/live/test_readonly_agent.py -q -rs`；唯一一次本轮新批次运行，exit 0，1 test passed，**9/9 attempts**。固定原题和顺序未缩窄，按 Q1/Q2/Q3 各三次。
- 新批次 `20261025T050032Z`：Q1目标缺口 **3/3**，Q2七天筛选/供应商推荐 **3/3**，Q3无有效报价 **3/3**。每次均记录 `model_mode_expected=live`、原始事件、持久化事件、Run快照、工具/查询证据、最终答案、验收理由和业务库 before/after。
- 九次业务库快照均逐记录相等：订单2、订单操作0、已消费审批0；W01库存、P001/P003报价与供应商状态均未变化。无订单写入。
- 完整脱敏尝试记录（包含此前三批失败）在 [P06-fix2-live-p03.json](P06-fix2-live-p03.json)，36条尝试均保留：`20261025T041535Z` **3/9**（Q1/Q2出现 `FACT_CHECK_FAILED`，缺少完整目标缺口/7天结论）；`20261025T043018Z` **3/9**（Q1出现 `REVIEW_FAILED`，Q2 `FACT_CHECK_FAILED`）；`20261025T044023Z` **7/9**（Q3两次被正确拒绝为完整报价集合/无有效报价证据不足）；最终 `20261025T050032Z` **9/9**。这些是不同代码/修复节点下的实际调用，不把旧失败回放或重试成功伪称首轮通过。四批每次 DB 前后快照均相等。脱敏证据已执行本机密钥值匹配扫描，未发现匹配。

## 历史状态、远程检查与未验项

- P03-A06：本轮固定新3×3达到9/9，P03相关 offline/browser/full regression 也通过。提交 `7f69ff12a1a3d33d80b8e9a798c5bef65aa32de3` 的 Linux Actions run [40165201596](https://github.com/newerwell/technologyagent/actions/runs/40165201596) 中 `p06-offline` job success；该提交同时是核准 `phase-p03` 的代码目标。
- Linux CI失败轨迹保留：run [40164481513](https://github.com/newerwell/technologyagent/actions/runs/40164481513)因pytest输出尾部截断而未保留两项集成错误正文；run [40164880332](https://github.com/newerwell/technologyagent/actions/runs/40164880332)在干净Linux runner上因`.runtime` basetemp父目录不存在导致2项集成错误。分别补上失败报告保留与临时目录父级创建及确定性回归后，run 40165201596通过；失败记录不覆盖。
- 当前实现远程SHA：`origin/main=7f69ff12a1a3d33d80b8e9a798c5bef65aa32de3`，与本地一致。P03验收门槛通过；annotated tag `phase-p03`已推送并核对，解引用SHA=`7f69ff12a1a3d33d80b8e9a798c5bef65aa32de3`。`phase-p04`和`phase-p05`保持原位。
- P06的其他正式验收仍未关闭：真实后端授权下载的浏览器端到端字节检查；其他报告格式的实际打开/视觉核对；已排队的 Codex 面板状态。HTML由用户确认显示正常、三类图表的历史视觉检查继续按原证据记录，不扩展为上述项目的通过。
- 因 P06严格门槛未全部关闭，本轮不创建 P06 完成标签、不移动旧标签、不开始 P07。
