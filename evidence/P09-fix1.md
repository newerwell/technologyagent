# P09-fix1 修复与补验收记录

日期：2026-10-26。范围为 P09-followup F01–F09 与 P09 前置残留；不开始 P10。该记录按独立任务追加，旧阶段标签不移动。

## F01：F12 判分与 live attempt 门禁

- 历史证据 `evidence/P09/live/F12-preference-complete-traces.json` 保持原样。只读统计确认 3 组、9 次 query、9 个旧 `passed=true`；9 次终态均为 `failed`，9 次终态 `review_passed=false`。旧分数是验收代码缺陷的证据，不代表通过。
- 新增验收 oracle：设置偏好和后续查询分别校验 live 模式、完整连续事件、completed 终态、review、无 error、owner偏好持久化、W01成功结构化工具事实、P001/55套最终回答与业务库前后快照。
- 新增 wrapper 回归：pytest 全 skip、空summary、部分 skip 均拒绝；子进程 timeout留下失败记录，同一逻辑 attempt 再执行生成另一个证据文件，不覆盖前次。每个 attempt 在 seed 前记录开始时间，并原子写入轨迹。
- 定向检查：`uv run pytest tests/unit/test_final_acceptance_oracle.py tests/integration/test_p09_live_gate.py -q`，exit 0，9 passed。此处是确定性测试，不是真实模型验收。
- 新的 P09 live 批次尚未运行；不把历史轨迹重放或现有 fake 运行记作新 live 通过。其余 P09 必需门槛尚未关闭，不创建 `phase-p09`。
