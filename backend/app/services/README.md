# services 应用服务

## 职责

P00/P01 服务：

- `SessionService`：生成随机 opaque token，以 HMAC-SHA256 保存摘要，设置 24 小时过期；`resolve()` 只接受有效未过期会话。
- `ReadinessService`：检查 DB ping、primary，执行一次真实事务写入并回滚，确认回滚后无残留，再汇总 model/mcp/sandbox 的 disabled 状态。
- `seeding.seed()`：校验 fixtures、核对 manifest、幂等 upsert 合成数据；`--reset` 只允许测试库。
- `CatalogService`：目录/报价分页读取，报价 `is_valid` 由后端时间和供应商状态判定。
- `InventoryService`：库存分页、预警全量过滤后分页、全量汇总。
- `ReplenishmentService`：一次拉齐 parts/inventory/quotes/suppliers，调用纯函数，返回 snapshot_versions 与 SourceRef。

## 公开接口

```python
record, raw_token = await session_service.create_local()
record = await session_service.resolve(raw_token)
result = await readiness_service.check()
```

## 边界

- 服务不读取请求体身份；owner 由 SessionService 固定为 `local-owner`。
- P01 不包含聊天、模型、审批或订单执行；补货公式只在 `domain/replenishment.py`。
- `/ready` 的事务探针使用独立随机 `_id`，回滚后断言文档数为 0。
- seed 默认不删除数据；`--reset` 对非 `technologyagent_test_*` 数据库直接失败。
