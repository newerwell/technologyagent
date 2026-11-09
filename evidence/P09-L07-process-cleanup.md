# P09 L07：Windows 测试进程树与临时证据隔离

日期：2026-11-09。实现提交 `41a95770ffb45501f735ed9a4130f42f2465325c`，远端 `origin/main` 已核对为同一 SHA。本证据记录 L07 的 Windows 离线稳定性，以及该 SHA 上已完成的 offline/browser 和 live 阻塞状态。

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

- 精确 SHA CI：run `42609691569`，head SHA 匹配 `41a95770ffb45501f735ed9a4130f42f2465325c`；`p09-offline`、`p06-offline` 均 success。
- Offline：`.runtime/reports/P09-L07-20261109-41a9577-offline.json`，8/8 必需检查通过；`tests/unit` + `tests/integration` 为 **724 passed**，完整命令 exit 0。
- Browser：`.runtime/reports/P09-L07-20261109-41a9577-browser.json`，seed与 full browser E2E 均 exit 0；Playwright **17 passed**。实际结果含报告下载、订单批准与恢复、重复批准幂等、改单 60 件/72000 分及桌面/手机视口。截图：`evidence/screenshots/P09-R8-L07-20261109-41a9577-browser-desktop-1440x900-{reports-downloaded,order-approved,approval-restored}.png` 与对应 `mobile-390x844` 三张。
- 固定 13 项 live：**not_run**。只读配置显示目标主机 `api.deepseek.com`、模型配置已存在；没有发出模型请求。自动审批拒绝理由为 live 将向该外部服务发送验收业务请求，而该审批要求额外明确目的地及发送内容。该批固定内容是合成 fixture：P03 三个只读问题各三次，加 F04 订单、F08 订单说明修订、F11 专家和 F12 偏好三次组。收到明确授权前不得启动。
- 此批 live 未生成 attempt 记录，也没有新的 live 数据库变更；历史失败批次不覆盖、不挑样例。未创建或移动阶段标签；真实 ERP F15/F16 未运行。
