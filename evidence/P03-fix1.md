# P03-fix1 补修证据

日期：2026-10-24
仓库：`C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent`
基线：`05e66c4638a3311beeddf02032c3439cbc728453` (`main` = `origin/main`)
计划标签：`phase-p02-fix1` → `d493ca5ea8d613f4042f3bd4f94a32b0237cc2ea`；保留原标签。
状态：implemented + offline_verified + browser_verified；live `not_run`，P03 最终验收未完成。

## 范围与约束

按 2026-10-24 P03 review 的 F01–F09 修复 R01–R09，并关闭 P02-R02 同视图旧刷新窗口。维持既有 ModelPort/GraphExecutor/ToolRegistry、事件和历史协议边界；工具仍为原 9 项只读工具。没有订单写入，没有 reset 开发库，没有开始 P04。未跟踪的 `.dsh-meow/` 与 `frontend/AGENTS.md` 不纳入本次变更。

## 修复与确定性反例

| 审查项 | 修复/失败断言 |
|---|---|
| R01 工具调用分片 | Adapter→GraphExecutor 用例交错两个 index，id/name 仅首片、arguments 多片；验证每个调用只执行一次且参数完整。非法最终 JSON 不执行。|
| R02 结构化事实 | `tests/unit/test_evidence.py` 拒绝 shortage 55→999、66000 分→999999 分、无关 supplier、P001/W01 跨实体/仓库声明；单位换算 660.00 元通过。事实保留 call_id、record、字段、值、单位、scope/as_of。|
| R03 先校验再发布 | 集成断言错误数值/“已下单”正文不会出现在 sink 的正式 token/message；只在最终业务校验成功后发布。|
| R04 总时限 | 可控时钟覆盖 deadline 前最后一次模型/工具调用不得越过总时限；单次 timeout 被剩余时间裁剪。|
| R05 同视图旧刷新 | hook deferred 失败用例：旧终态 refresh pending 时启动新 run，旧响应完成后新 run 仍 running 且接收新 token；Playwright 同流程通过。|
| R06 历史模式归属 | 固定历史 fixture 检查 live/fake 多轮逐消息标识，缺失元数据不猜成 live。|
| R07 提前 EOF | MockTransport 在 token/半截 tool args 后 EOF 必须报 `MODEL_PROTOCOL_ERROR`；持久终态失败并写 error/stream_end，不把残缺正文当成功。|
| R08 MCP 清理 | `tests/unit/test_mcp_registry_cleanup.py` 覆盖发现失败、取消、半初始化清理、清理异常保留原始错误、正常所有权交接；均验证 close 次数。|
| R09 假 live/空 manifest | 验收单测拒绝 scripted/fake、失败终态、工具错误、缺终事件、工具缺失/参数不符/无事实等假成功；P03 live manifest 非空。缺真实配置时必须 `not_run`。|

相关确定性用例：`tests/unit/test_model_adapter.py`、`tests/unit/test_evidence.py`、`tests/unit/test_live_acceptance.py`、`tests/unit/test_mcp_registry_cleanup.py`、`tests/integration/test_agent_tools.py`、`tests/integration/test_agent_stream.py`、`frontend/src/hooks/useChat.test.tsx`、`frontend/src/components/chat/MessageList.test.tsx`、`tests/e2e/chat-flow.spec.ts`。

## Offline 与 browser

| 检查 | 结果 |
|---|---|
| P03 offline manifest | `uv run python -m scripts.verify_stage P03 --mode offline --report .runtime/reports/P03-fix1-offline.json`，exit 0，9/9 checks，181.72 秒。|
| Backend unit | 49 passed。|
| Backend integration | 92 passed。|
| Frontend | typecheck/build passed；7 files、25 tests passed。|
| Contract generation | `uv run python -m scripts.export_contracts --check`，exit 0，contracts up to date。|
| P03 browser manifest | `uv run python -m scripts.verify_stage P03 --mode browser --report .runtime/reports/P03-fix1-browser.json`，exit 0；Playwright 7/7 passed。|
| Browser cleanup | `stop.ps1` 成功停止 MCP/backend/frontend；Mongo 保持运行。独立 DB `technologyagent_test_p03_browser` 检查为不存在。|
| Source hygiene | `git diff --check` exit 0；`py_compile` 对 live test 与 acceptance helper exit 0。|

Offline manifest 的 DB 初始化只用 `technologyagent_test_p03_offline`，seed/reset 目标为 `technologyagent_test_p03_verify`。P03 浏览器用例运行前使用专用 `technologyagent_test_p03_browser` 配置；完成后确认该库不存在。没有使用或 reset `technologyagent_dev`。

## Live 状态

当前没有 `MODEL_API_KEY`、`MODEL_NAME`，也没有 `RUN_LIVE_MODEL=1`。通过项目 Python 直接执行 live manifest 返回：`P03 live: not_run (explicit live configuration or isolated test database missing)`，exit 2，报告 `.runtime/reports/P03-fix1-live.json`。没有请求真实供应商；固定 3 个问题各 3 次尚未运行，不能据此宣称 P03 最终验收完成。

配置和显式启用齐备后，才运行 `tests/live/test_readonly_agent.py` 固定的 3×3；保存全部成功/失败/纠错轨迹和调用参数/结果/事实，脱敏后与独立测试库 seed 数据逐条对照。9 次必需验收均通过后，提交最终记录、创建并核对 annotated `phase-p03`。当前不创建标签、不开始 P04，交付后等待复核。

## 远程交付

补修实现提交：`d64177b1331b7d1c51510ce77459f8b7f94f9d0e` (`fix(p03): close review gaps and strengthen acceptance`)。
推送核对：`origin/main` = `d64177b1331b7d1c51510ce77459f8b7f94f9d0e`，与本地 `HEAD` 相同。
GitHub Actions：[run 40067594848](https://github.com/newerwell/technologyagent/actions/runs/40067594848) success；`p03-offline`、manifest 检查及验证报告上传步骤均成功。
旧标签：本地和远程 `phase-p02-fix1` 解引用均为 `d493ca5ea8d613f4042f3bd4f94a32b0237cc2ea`，未移动。
没有创建 `phase-p03`；P04 未开始。交付记录后续有独立文档提交，CI 成功对应上述实现提交。
