# P09 L07 live wrapper：Windows 子进程 UTF-8 解码

日期：2026-11-09。候选 `4409a577a958cd8962b9b4462c8c07b45f628a86` 已完成本机 offline、精确 SHA CI 与 browser；固定 live 批次实际执行后发现 live wrapper 在 Windows 默认代码页下解码不完整。本修复形成新候选，须重新完成四项 L07 门禁。

## 反例、修复与定向验证

- 本批 `.runtime/live/p09/attempts/20261109T093943Z-f0e73fade8/summary.json` 记录了固定排程全部 **13** 条外层尝试，**5 passed、8 failed**。8项失败均无完整 pytest summary；外层 pytest stderr 的 `Thread-*_readerthread` 给出 `UnicodeDecodeError: 'gbk' codec can't decode byte 0xae`。F04 两过一失败、F12三次通过，其余8失败；失败不能归因为模型事实错误，因为对应子进程正文没被完整解码。
- 新增 `test_live_attempt_decodes_unicode_subprocess_output_as_utf8`，旧实现没传 `encoding/errors` 时确定性失败。实现将子进程读取固定为 `encoding="utf-8", errors="replace"`，避免 Windows locale 对 UTF-8 轨迹造成 reader-thread 丢失。
- 定向命令：`uv run python -m pytest --basetemp .runtime/pytest-L07-live-utf8-green tests/integration/test_p09_live_gate.py -q -rs`，**7 passed，exit 0**。RED 为单个新反例 **1 failed**；首次RED没有pytest setup权限问题。

## 该候选完整门禁（保留但不作为新候选通过）

- Offline：`.runtime/reports/P09-20261109-172403-offline.json`，8/8 required passed，Python **712 passed**，exit 0。
- 精确 SHA CI：run `42593031778`，head SHA 匹配上述候选，`p09-offline` 与 `p06-offline` success。
- Browser：`.runtime/reports/P09-20261109-172403-browser.json`，seed和 `npm --prefix frontend run test:e2e -- --workers=1` 均exit 0；E2E **17 passed**。桌面/手机下载、订单批准/恢复事实有本批截图；浏览器 responsive 测试会覆盖固定名称截图，因此新输出已另存为batch路径，固定名称原图从现存fresh-checkout证据副本恢复。新候选仍需重新跑这些门禁。
- Live：`.runtime/reports/P09-20261109-172403-live.json` exit 1；13外层5/8。全部原始attempt JSON与summary保留在`.runtime/live/p09/attempts/20261109T093943Z-f0e73fade8/`，没有挑选或重写结果。
- Live数据库最终只读快照（无本批开始前的count基线，故不归因写入delta）：`technologyagent_test_p09_live` orders=2、approvals=12、operations=12、receipts=0、inventory_movements=0、drafts=2；P001/W01 `on_hand=20,reserved=5,inbound=10,version=1`。这些值是结束时事实，不能替代每个场景前后对照。
- 本机完整模型/业务答案未因解码器回归而重新执行；必须在此修复后的新SHA上重跑固定排程，全部失败和成功轨迹都保留。未创建`phase-p09`；F15/F16真实ERP未运行。
