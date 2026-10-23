# repositories 数据访问

## 职责

封装 MongoDB 连接、事务、collection 约定和 P00 会话摘要存储。路由与 services 不直接创建 `AsyncMongoClient`。

## 公开接口

- `MongoResources.connect()/open(settings)/close()/transaction()/ping()/hello()`：连接生命周期与真实事务上下文。
- `ensure_indexes(db)`：幂等创建 `sessions`、`system_meta`、`_health_probe` 与 TTL/owner 索引，写入 `schema_version=1`。
- `SessionRepository.insert(record)/find(token_hash)`：只保存 HMAC 摘要，不保存原始 token。

## 例子

```python
resources = await MongoResources.open(settings)
async with resources.transaction() as session:
    await resources.db["example"].insert_one({"x": 1}, session=session)
await resources.close()
```

## 边界与验证

- `transaction()` 必须连接 replica set；standalone 会失败，不会退化为单文档写入。
- collection 名集中定义在 `indexes.py`；P00 不创建业务 collection。
- 测试库必须以 `technologyagent_test_` 开头；`tests/integration/test_mongo_transactions.py` 验证真实提交/回滚。
