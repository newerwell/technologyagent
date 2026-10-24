# services 应用服务

## 职责

P00/P01/P02 服务：

- `SessionService`：生成随机 opaque token，以 HMAC-SHA256 保存摘要，设置 24 小时过期；`resolve()` 只接受有效未过期会话。
- `ReadinessService`：检查 DB ping、primary，执行一次真实事务写入并回滚，确认回滚后无残留，再汇总 model/mcp/sandbox 的 disabled 状态。
- `seeding.seed()`：校验 fixtures、manifest 与“未关闭订单剩余量 = inventory.inbound”对账，默认只补齐缺失的固定记录（`$setOnInsert`），不覆盖已有记录/version；`--reset` 只允许测试库。
- `baseline_repair.repair_p01_baseline()`：显式修正旧 I004/I006/I007 基线；默认 dry-run，`--apply` 在事务内执行，遇到修改过的库存或相关新增订单拒绝覆盖。
- `CatalogService`：目录/报价分页读取，报价 `is_valid` 由后端时间和供应商状态判定。
- `InventoryService`：库存分页、预警全量过滤后分页、全量汇总。
- `ReplenishmentService`：一次拉齐 parts/inventory/quotes/suppliers，调用纯函数，返回 snapshot_versions 与 SourceRef。
- `RunService`：thread/run/message/event 事务、request_id 幂等、seq 原子递增、终态与启动孤儿失败恢复；删除先条件认领 thread（active_run_id=None 且 deleting!=true），与创建认领互斥。
- `RunService.create_or_get` 在每次事务/竞争重试重查 owner/request_id/hash，返回 `(RunView, just_created)`。
- `ChatService`：后台任务管理器 + FakeAgent；budget 先于 run_started 注册，执行器启动前同步持久 cancel_requested；SSE 只观察持久事件，观察连接关闭不取消任务。
- SSE 观察在终态后继续排空到 last_seq，不因一次空 events 查询漏 stream_end。

## 公开接口

```python
record, raw_token = await session_service.create_local()
record = await session_service.resolve(raw_token)
result = await readiness_service.check()
report = await repair_p01_baseline(mongo, apply=False)  # 默认 dry-run
run = await run_service.create(None, "hello", "request-1", ctx)
await chat_service.start(None, "hello", "request-1", ctx)
```

## 边界

- 服务不读取请求体身份；owner 由 SessionService 固定为 `local-owner`。
- P01 不包含聊天、模型、审批或订单执行；补货公式只在 `domain/replenishment.py`。
- P02 的 `ChatService` 只使用 FakeAgent；真实模型/工具执行是 P03。
- P02 启动恢复只把遗留非终态 run 标 failed/PROCESS_RESTARTED，不是 checkpoint 恢复。
- `/ready` 的事务探针使用独立随机 `_id`，回滚后断言文档数为 0。
- seed 默认不删除也不覆盖数据；`--reset` 对非 `technologyagent_test_*` 数据库直接失败。
- 旧基线修正不是 API 启动迁移，也不接受 `--reset`；冲突时报告并停止。
- FakeAgent 的 token/工具事件只用于协议验收，不调用真实模型或业务写入。
