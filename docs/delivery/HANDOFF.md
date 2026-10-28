# P09 最终补修交接

stage: P09-final-closure
current_task: 任务卡3实现和定向单测已完成；Mongo集成待副本集环境恢复后补验，按手册要求暂不进入任务卡4
base_head: d7a4907714b0dde01cf9ddc0afaeab37604f6c75
base_origin_main: d7a4907714b0dde01cf9ddc0afaeab37604f6c75
working_tree: 任务卡3源码已提交推送；当前交付记录待提交；复审材料、截图、.dsh-meow/、frontend/AGENTS.md保留，不纳入提交
previous_phase_tag: 不移动任何旧标签；不创建phase-p09

## 本卡已完成

- 订单写事务内持久化来自服务端核验记录的`verification_facts`，常规订单API剥离此内部字段。
- 结算以提交时快照检查正文数量、金额、单号、已保存交期约束与报价交期；不向当前目录回查历史单位；没有收货事实时拒绝肯定收货语句。
- 语义评审只获必要白名单字段；正文可修订两次但不能重放提交。
- 定向单元回归13 passed；完整unit 270 passed。
- 任务卡3提交`d7a4907714b0dde01cf9ddc0afaeab37604f6c75`已推送，`origin/main`一致；GitHub combined status没有返回CI checks，CI未核实。
- Mongo集成无法执行测试体：本地27027是standalone，测试要求`ta-rs`副本集；Docker daemon不可用。证据见`evidence/P09-fix4.md`。

## 仍未完成

- 本卡Mongo集成回归尚未通过/运行；P09完整offline/browser/live和真实模型批次尚未运行。
- 任务卡4–11未执行；本地最终矩阵尚未关闭。
- 不创建`phase-p09`，不开始P10。

last_command: `uv run python -m pytest --basetemp .runtime/pytest-task3-unit tests/unit -q -rs`
last_exit_code: 0
last_error: `tests/integration/test_order_review_loop.py` requires local Mongo replica set `ta-rs`; current endpoint identifies as standalone.
