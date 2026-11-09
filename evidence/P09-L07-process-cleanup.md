# P09 L07：Windows 测试进程树与临时证据隔离

日期：2026-11-09。当前候选基于 `bd5c0adefffa2450c9d8805306eb1bb79a165d56`，本次改动尚未提交；本记录只覆盖 L07 的 Windows 离线门禁稳定性，不表示 offline/browser/live 全部通过。

## 反例与根因

- 真实 Next→Uvicorn 测试结束后，Next 的 Node 启动包装器可能已退出，而其 Next worker 仍存活并占用 `.next` 开发锁。旧 `_stop_process` 仅在 `Popen.poll() is None` 时运行 `taskkill /T`，因此无法清除“根进程已退出、子孙进程仍在”的树。
- 在 `tests/integration/test_local_startup_boundary.py` 增加 `test_stop_process_kills_tree_even_if_launcher_exited`。修复前实测 **1 failed**，断言 taskkill 未被调用；不是环境启动失败。
- `test_live_wrapper_records_timeout_and_never_overwrites` 将数据写在仓库 `.runtime` 子目录。在本机 ACL 下，重复原子替换实际报 `PermissionError: [WinError 5]`。该路径与 pytest 临时目录隔离无关，故两个 wrapper 测试现改用 `tmp_path`。

## 修复与验证

- Windows `_stop_process` 对传入的测试专属 PID 始终运行 `taskkill /T /F`，再等待根进程；POSIX 的进程组行为不变。
- 新进程树单测与两个 wrapper 证据测试：`uv run python -m pytest ...`，**3 passed，exit 0**。
- 真实集成和 gate 模块：`tests/integration/test_local_startup_boundary.py tests/integration/test_p09_live_gate.py`，**9 passed，exit 0**；包含实际 Next→Uvicorn HTTP/session 链路。
- 同一组合在修复前曾 **6 passed、2 failed**：Next 连接拒绝（另一次测试留下的 Next worker 占锁），以及上述 Windows `.runtime` 原子替换 ACL 错误。确定性复现由新进程清理单测保留。
- 组合通过后按项目路径查询 Next 测试进程，无本次 `run-next.mjs`/Next dev 进程残留。

## L07 门禁状态

此测试修复之后尚未运行新候选的完整 offline、精确 SHA CI、browser 或固定 13 项 live；当前状态为 **not_run**。已有旧 SHA 的 offline/browser/live 记录仍按原批次保留，不能挪用为本候选证据。未创建或移动阶段标签；真实 ERP F15/F16 未运行。
