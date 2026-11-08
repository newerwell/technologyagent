# P09 最终补修交接

stage: P09-final-closure
current_task: R0隔离副本集与任务卡3 Mongo补验通过；当前工作区待R0交付提交，下一卡R1停用物料缺库存标记
base_head: 3d4b4ba04d655747f566260dc12ac00273adad29
base_origin_main: 待本卡提交后核对（本机受限网络下ls-remote失败）
working_tree: 本卡仅修改启动脚本、隔离Compose/环境脚本、定向测试、模块说明与R0证据；既有复审文档、截图、.dsh-meow/、frontend/AGENTS.md及用户提供实施文档保留未暂存
previous_phase_tag: 不移动任何旧标签；不创建phase-p09

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
- 代码/evidence/README更新尚未提交。当前`uv run`缓存ACL限制，定向Python通过仓库`.venv`运行。默认沙箱`git ls-remote origin`拒绝网络；提交后须申请网络访问推送并核SHA。
- 下一步R1先确认缺库存停用物料反例和差异，再修复测试；本任务完成前不推进R1。
