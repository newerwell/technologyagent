# P09 L07 preflight：验收业务时钟格式

日期：2026-11-09。L07 browser 启动前发现并修复验收环境助手的时钟编码问题；因此原候选 `a6c63aafadd8d584e00b6c852b8f2072c2f5f88b` 的 L07 报告不作为新候选门禁证据，新候选需重新完成 offline、CI、browser 与 live。

## 反例与结果

- `fixtures/v1/manifest.json` 的 `fixed_now` 原文为 `2026-10-23T02:00:00Z`。PowerShell `ConvertFrom-Json` 默认转换为 DateTime，再经 `[string]` 输出为 `10/23/2026 02:00:00`；`start.ps1` 因 `Settings.acceptance_business_now` 不是 ISO datetime，在数据库初始化前退出。
- 新增 `test_acceptance_business_clock_remains_iso8601`。旧实现的确定性结果为 **1 failed**，实际值是区域化的 `10/23/2026 02:00:00`；第一次pytest启动被系统临时目录ACL阻断，没有算作产品反例。使用新仓库隔离basetemp后复现。
- 修复为以 `.NET System.Text.Json.JsonDocument` 读取原始字符串；不做本地时区或区域格式转换。`tests/unit/test_p09_acceptance_environment.py` 为 **10 passed，exit 0**。

## 被此修复作废的候选尝试

在发现浏览器启动缺陷前，候选 `a6c63aaf...` 的 offline retry3 为8项检查全部通过，其中 Python **712 passed**、Docker必需用例实际运行；但该源码随后因本修复改变，retry3不构成新SHA的验收。保留旧批次所有输出：首次ACL/Docker权限失败、第二次因验收遗留Next dev进程而`711 passed / 1 failed`、定向Next启动回归 **1 passed**、retry3 **712 passed**。第二次的Node进程只按已核实命令行清理。

该 SHA 的 push CI run `42588162165` 曾以 `p09-offline` 与 `p06-offline` success 结束；修复提交后的新SHA必须重新核CI。尚未运行有效的新候选browser或live，不创建`phase-p09`。
