# P09 隔离数据库与文件备份恢复

源库 `technologyagent_test_p09_browser`，恢复目标 `technologyagent_test_p09_restore3`。脚本要求维护确认、应用无项目进程、目标为专用测试库且为空；未对开发库执行清空或恢复。

| 数据 | 备份源 | 恢复后 | 结果 |
|---|---:|---:|---|
| runs | 45 | 45 | 一致 |
| orders | 3 | 3 | 一致 |
| approvals | 12 | 12 | 一致 |
| artifacts | 1 | 1 | 一致 |
| events | 693 | 693 | 一致 |
| lg_checkpoints | 21 | 21 | 一致 |
| lg_checkpoint_writes | 105 | 105 | 一致 |
| storage 文件 | 11 | 11 | 文件清单及SHA-256一致 |

恢复后的artifact文件SHA-256：`D4384E05186D50201D688CADA5E373A080AA0CCAEFE7C7A222F111030BB909F5`。

这是真实MongoDB与storage目录复制/恢复检查。`uv sync --frozen --group dev`、`npm --prefix frontend ci` 成功，但没有从全新克隆目录完成启动，所以P09-A01/P09-A06仅部分覆盖。
