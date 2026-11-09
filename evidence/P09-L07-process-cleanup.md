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
- 本轮获得用户明确授权后，固定 13 项 live 已运行；使用 `technologyagent_test_p09_live`、合成 fixtures，模型端点 `api.deepseek.com`。批次报告：`%TEMP%/P09-L07-20261109-212626-live.json`，退出码 **1**，耗时 527.7 秒。批次目录：`.runtime/live/p09/attempts/20261109T132629Z-01573fa3ae/`，包含 summary 与全部 13 条唯一 attempt 记录；P03 内部九次轨迹追加在 `.runtime/live/p03-readonly.json`，P04、P07 详细轨迹分别追加/写入 `.runtime/live/p04-order-workflow-attempts.json` 与 `.runtime/reports/P07-live-20261109T133121Z.json`、`...133258Z.json`、`...133426Z.json`。历史轨迹保留，未覆盖或挑选成功记录。
- Live 汇总：**8/13 通过，5/13 失败**。F04 order 2/3（失败项是批准后缺少预期的 completed 事件）；F08 order review 3/3；F11 specialists 0/3（失败终态由严格评审的 `NUMERIC_MATCH`、`SCOPE_MATCH`、`SUPPLIER_RECOMMENDATION_COVERAGE` 等触发，没有生成审批等待）；F12 preferences 3/3；P03-A06 固定三题九次为 **2/9**（第1题0/3、第2题0/3、第3题2/3）。P03失败轨迹显示事实/范围校验和一次 `KeyError` 工具循环错误；本批未观察到连接中断/超时，不能将这些错误归因于传输层。
- P03 每次数据库核验均基于同一合成业务事实：P001/W01 缺口55、有效报价Q01/S01、5天、66000分；P003唯一报价Q06已过期；P003/W01缺口36，P004/W01缺口10。九条只读轨迹没有订单写入；测试断言的 `on_hand=20`、`inbound=10` 保持不变。失败原因包含数字/字段绑定、范围、答案覆盖及一次 `KeyError`，属于未通过的业务/执行验收，不标为模型网络失败。
- F04 两次通过项及一次在提交后失败的项都保存了事务证据。失败项仅在 `run_finished=completed` 事件断言处失败；数据库事实显示订单数 **2→3**、`order_create` operation **24→25**、已消费审批 **24→25**、P001 inbound **10→65**、on_hand仍为 **20**，订单为55套、总额66000分，只有一张新订单；没有因说明/事件验收失败再次提交。两次通过项也各自只有一张新订单，数量55、总额66000分，库存事实同为 on_hand20、inbound65。
- F11 三次失败都保持订单数与 `order_create` operation 数不变；I001 on_hand20/inbound10 未变，每次仅生成一个分析 artifact。F08、F12 三次均通过。
- 完整 Offline：`%TEMP%/P09-L07-20261109-211401-offline.json`，8/8 必需检查 exit 0，含单元/集成、前端类型检查、E2E类型检查、47个前端测试、build 与契约检查。完整 Browser：`%TEMP%/P09-L07-20261109-205531-browser.json`，seed exit 0、Playwright 17 passed，桌面/手机流程均通过。
- L07 的 offline 与 browser 门禁关闭；live 门槛仍未关闭，因此本轮不称 P09 完成、不创建/移动阶段标签，也不执行 L08/L09。真实 ERP F15/F16 未运行。
