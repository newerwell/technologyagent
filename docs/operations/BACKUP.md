# 一致备份与恢复

当前脚本只允许以 `technologyagent_test_*` 数据库做演练。先停止本项目应用进程、MCP业务进程并确认无在途写，再执行：

```powershell
./scripts/backup.ps1 -DatabaseName technologyagent_test_p09_verify -Destination .runtime/backups/p09-<时间戳> -MaintenanceConfirmed
./scripts/restore.ps1 -BackupDirectory .runtime/backups/p09-<时间戳> -TargetDatabase technologyagent_test_p09_restore -TargetStorageDirectory .runtime/restore/p09-<时间戳> -MaintenanceConfirmed
```

备份包含Mongo归档和 `storage/` 文件，manifest记录每个文件的SHA-256与长度。恢复先检查manifest、哈希、测试库名前缀和目标库空状态，再将来源命名空间重映射到新的隔离测试库，并恢复到新的存储目录。不要把目标参数改为日常或生产库。演练通过后，再分别核对订单、审批、checkpoints、artifact元数据与文件关联。

如果归档或文件哈希不符，脚本会停止；不要跳过校验或覆盖目标。应用停止和无在途写的检查属于操作者维护窗口责任，脚本的 `-MaintenanceConfirmed` 是显式断言，不替代实际确认。
