# 一致备份与恢复

当前脚本只允许以 `technologyagent_test_*` 数据库做演练。先停止本项目应用进程、MCP业务进程并确认无在途写，再执行：

```powershell
./scripts/backup.ps1 -DatabaseName technologyagent_test_p09_verify -Destination .runtime/backups/p09-<时间戳> -MaintenanceConfirmed
./scripts/restore.ps1 -BackupDirectory .runtime/backups/p09-<时间戳> -TargetDatabase technologyagent_test_p09_restore -TargetStorageDirectory .runtime/restore/p09-<时间戳> -MaintenanceConfirmed
```

备份使用manifest format 2，记录来源DB实际namespace、完整artifact引用（owner/run/status/storage_key/size）和全部文件SHA-256/长度。备份前检查DB ready artifact与StorageRoot文件集合完全相同；有ready artifact时缺失或拼错StorageRoot会失败，只有DB没有artifact引用时才允许空storage。storage参数会按传入的精确目录处理。

恢复在写入前对归档执行真实`mongorestore --dryRun --verbose`并提取归档namespace，要求与manifest完整相等且全部属于来源测试库；实际恢复还显式使用该来源的`--nsInclude`、`--nsFrom`和新测试库`--nsTo`。恢复目标collection非空、归档多库/错库、文件清单多项/缺项/哈希/长度不符、reparse point或storage文件与artifact关联不符都会失败。恢复后比对目标artifact记录，再复制文件并核对文件长度。不要把目标参数改为日常或生产库。演练后另核对订单、审批、checkpoints及授权下载。

如果归档或文件哈希不符，脚本会停止；不要跳过校验或覆盖目标。应用停止和无在途写的检查属于操作者维护窗口责任，脚本的 `-MaintenanceConfirmed` 是显式断言，不替代实际确认。
