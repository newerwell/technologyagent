# repositories 数据访问

## 职责

封装 MongoDB 连接、事务、collection 约定、P00 会话摘要、P01 目录/库存读取、P02 thread/run/message/event 持久化、P03 MCP 短期 token 摘要，以及 P04 草稿/订单/操作结果和 LangGraph 持久检查点。路由与 services 不直接创建 `AsyncMongoClient`。

## 公开接口

- `MongoResources.connect()/open(settings)/close()/transaction()/ping()/hello()`：连接生命周期与真实事务上下文。
- `ensure_indexes(db)`：幂等创建 `sessions`、`system_meta`、`_health_probe` 与 TTL/owner 索引，写入 `schema_version=1`。
- `SessionRepository.insert(record)/find(token_hash)`：只保存 HMAC 摘要，不保存原始 token。
- `CatalogRepository.search_parts/search_suppliers/get_*/list_*/page_quotes`：固定按 `_id` 排序，count 与 records 共用 filter。
- `InventoryRepository.page/get/list_scope/list_all`：part_name 筛选先查 parts 得到 ID；list_scope 返回全部指定范围。
- `RunRepository`：thread 认领/释放、删除条件认领（`claim_for_delete` 设置 deleting）、run、request_id 查询、事件 seq、模型/工具调用计数、decision_history、active_seconds_used和跨resume起始时刻、批量删除；`MessageRepository`：user 一次插入、assistant 固定 id 幂等 upsert。
- `McpTokenRepository`：保存短期 MCP token 的 SHA256 摘要、owner/run/actor、expires_at，供 MCP 服务解析 Bearer。
- `DraftRepository`：owner-scoped 查询草稿；持久化库存版本和报价快照；更新使用 expected_version CAS。
- `OrderRepository`：owner-scoped 订单列表/详情；创建只接受事务 session，并绑定 operation_id。
- `OperationRepository`：owner/action/key 唯一认领 120 秒租约；新订单操作保存run_id，事务内保存 succeeded 结果。
- P08 `MovementRepository` 使用 `receipts` 与 `inventory_movements`；Receipt按 `(owner_id,provider,receipt_id)` 去重，采购收货流水按同一作用域及零件/仓库唯一。库存、在途、订单已收量、审批与operation结果由服务在同一个Mongo事务协调。
- P08 `OrderRepository.search_details()` 在Mongo端先筛选owner/status/supplier/part再分页，避免对一页数据误报全量结果。
- `MongoResources.configure_checkpointer()`：持久 saver 使用独立同步 PyMongo 客户端和 `lg_checkpoints`、`lg_checkpoint_writes` collection。

## 例子

```python
resources = await MongoResources.open(settings)
async with resources.transaction() as session:
    await resources.db["example"].insert_one({"x": 1}, session=session)
await resources.close()
```

## 边界与验证

- `transaction()` 必须连接 replica set；standalone 会失败，不会退化为单文档写入。
- collection 名集中定义在 `indexes.py`；P01 建立 parts/suppliers 的 code 唯一索引、inventory 的 part+warehouse 唯一索引、order 的 number/draft_id 唯一索引；P02 建立 threads/runs/messages/events，`(owner_id,request_id)` 与 `(run_id,seq)` 唯一；P03 建立 `mcp_sessions` TTL 与 owner/run 索引。
- 测试库必须以 `technologyagent_test_` 开头；`tests/integration/test_mongo_transactions.py` 验证真实提交/回滚。
- `tests/integration/test_catalog.py` 验证分页、筛选 total、空结果与 404。
- `tests/integration/test_run_atomicity.py` 验证 request 去重、同 thread 单活跃 run、并发 seq、终态幂等、owner 条件、删除/创建事务互斥。
- `tests/integration/test_p02_fix1.py` 验证 run_started 窗口取消；`tests/unit/test_sse_drain.py` 验证终态排空。
- P04 索引含 pending approval、operation key、订单 operation_id 唯一约束；事务回归只用 `technologyagent_test_*` replica-set 库。
- P06 `ArtifactRepository`按artifact_id/owner_id读取元数据；内容留在服务端storage root的owner/run生成目录，不接受用户提供路径。
- P06 `list_for_thread(owner_id,thread_id)`先用owner验证threads归属，再聚合该线程所有RUNS下ready产物；投影不返回storage_key，UI可跨run恢复历史文件而不改当前run事件seq。

- P07 `PreferenceRepository`只按 `(owner_id,key)` 读写三项白名单显式偏好；唯一索引保证并发保存不产生重复记录。偏好值校验属于PreferenceService，repository不推断或自动写入用户习惯。
- P08 新增 `receipts` / `inventory_movements` 集合；成功收货事务回归：`uv run pytest tests/integration/test_inventory_receipts.py -q`。只允许在 `technologyagent_test_*` 库运行集成测试。
