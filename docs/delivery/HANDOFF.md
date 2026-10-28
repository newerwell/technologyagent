# P09 最终补修交接

stage: P09-final-closure
current_task: 任务卡 2 完成后，准备任务卡 3
base_head: 881ac46de956aff29e428f6d050cfa47d49f308e
base_origin_main: 881ac46de956aff29e428f6d050cfa47d49f308e
working_tree: 任务卡2代码、测试和文档待提交；复审材料、截图、.dsh-meow/ 和 frontend/AGENTS.md 保留未提交
previous_phase_tag: 无新增或移动；按后续实际检查核对既有标签

## 已完成

- 确认实际仓库、main、origin/main 与忽略规则。
- 任务0基线已提交、推送，SHA见`evidence/P09-fix4.md`。
- 停用物料预览及界面解释通过定向、全后端单元和typecheck回归，详见`evidence/P09-fix4.md`。
- 模型修订正文保留回归已通过；核验事实通过调用消息副本提供，详见`evidence/P09-fix4.md`。
- Mongo环境阻断、未完成门禁和本地快照边界见`evidence/P09-fix4.md`。

## 未完成

- 后续按 `docs/implementation/P09-final-closure.md` 顺序执行任务卡3–11。
- 未运行真实模型或真实ERP；真实ERP调用禁止，F15/F16保留not_run。
- 不创建 `phase-p09`，不开始P10。

last_command: `uv run python -m pytest --basetemp .runtime/pytest-task2-unit tests/unit/test_graph_answer_preservation.py tests/unit/test_verified_answers.py tests/unit/test_deterministic_review.py tests/unit/test_fact_checks.py -q -rs`
last_exit_code: 0
last_error: `tests/integration/test_inventory_snapshot_routes.py`未运行成功：本机Mongo副本集/Docker daemon不可用。
next_action: 显式暂存任务卡2文件，提交推送并核对远端SHA；然后先为任务卡3扩展提交后订单正文评审反例。
do_not_repeat: 不要读取/提交`.env`、原始库存或metadata；不要重置`technologyagent_dev`；不要覆盖或删除保留的复审材料与用户文件。
