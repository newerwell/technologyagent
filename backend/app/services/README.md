# services 应用服务

## 职责

P00 包含两个服务：

- `SessionService`：生成随机 opaque token，以 HMAC-SHA256 保存摘要，设置 24 小时过期；`resolve()` 只接受有效未过期会话。
- `ReadinessService`：检查 DB ping、primary，执行一次真实事务写入并回滚，确认回滚后无残留，再汇总 model/mcp/sandbox 的 disabled 状态。

## 公开接口

```python
record, raw_token = await session_service.create_local()
record = await session_service.resolve(raw_token)
result = await readiness_service.check()
```

## 边界

- 服务不读取请求体身份；owner 由 SessionService 固定为 `local-owner`。
- P00 不包含采购、补货、审批或订单服务。
- `/ready` 的事务探针使用独立随机 `_id`，回滚后断言文档数为 0。
