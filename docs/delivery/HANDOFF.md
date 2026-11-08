# P09 最终补修交接

stage: P09-final-closure
current_task: R2统一模型调用/预算/有限重试已验证；提交推送后开始R3
base_head: 3d4b4ba04d655747f566260dc12ac00273adad29
base_origin_main: 3d4b4ba04d655747f566260dc12ac00273adad29
working_tree: R2代码提交b8cf2c4cb0db00cd6502ed257b02783b2aa4107b已推送；交接SHA补录待文档提交。既有复审文档、截图、.dsh-meow/、frontend/AGENTS.md及用户提供实施文档保留未暂存
previous_phase_tag: 不移动任何旧标签；不创建phase-p09

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
