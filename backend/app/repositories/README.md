# repositories 数据访问

## 职责

封装 MongoDB 连接、事务、collection 约定、P00 会话摘要、P01 目录/库存读取，以及 P02 thread/run/message/event 持久化。路由与 services 不直接创建 `AsyncMongoClient`。

## 公开接口

- `MongoResources.connect()/open(settings)/close()/transaction()/ping()/hello()`：连接生命周期与真实事务上下文。
- `ensure_indexes(db)`：幂等创建 `sessions`、`system_meta`、`_health_probe` 与 TTL/owner 索引，写入 `schema_version=1`。
- `SessionRepository.insert(record)/find(token_hash)`：只保存 HMAC 摘要，不保存原始 token。
- `CatalogRepository.search_parts/search_suppliers/get_*/list_*/page_quotes`：固定按 `_id` 排序，count 与 records 共用 filter。
- `InventoryRepository.page/get/list_scope/list_all`：part_name 筛选先查 parts 得到 ID；list_scope 返回全部指定范围。
- `RunRepository`：thread 认领/释放、删除条件认领（`claim_for_delete` 设置 deleting）、run、request_id 查询、事件 seq、批量删除；`MessageRepository`：user 一次插入、assistant 固定 id 幂等 upsert。

## 例子

```python
resources = await MongoResources.open(settings)
async with resources.transaction() as session:
    await resources.db["example"].insert_one({"x": 1}, session=session)
await resources.close()
```

## 边界与验证

- `transaction()` 必须连接 replica set；standalone 会失败，不会退化为单文档写入。
- collection 名集中定义在 `indexes.py`；P01 建立 parts/suppliers 的 code 唯一索引、inventory 的 part+warehouse 唯一索引、order 的 number/draft_id 唯一索引；P02 建立 threads/runs/messages/events，`(owner_id,request_id)` 与 `(run_id,seq)` 唯一。
- 测试库必须以 `technologyagent_test_` 开头；`tests/integration/test_mongo_transactions.py` 验证真实提交/回滚。
- `tests/integration/test_catalog.py` 验证分页、筛选 total、空结果与 404。
- `tests/integration/test_run_atomicity.py` 验证 request 去重、同 thread 单活跃 run、并发 seq、终态幂等、owner 条件、删除/创建事务互斥。
- `tests/integration/test_p02_fix1.py` 验证 run_started 窗口取消；`tests/unit/test_sse_drain.py` 验证终态排空。
