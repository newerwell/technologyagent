# agent 执行器（P02）

## 职责

- `budget.py`：`RunBudget` 提供 `check_cancelled()` 与活跃 deadline；P03 再增加模型/工具原子计数。
- `fake_executor.py`：`FakeAgent` 只产生示例 token 和 `fake_readonly_catalog` 假工具事件，`simulation=true`；不访问真实模型或业务数据。

## 调用

```python
outcome = await FakeAgent().execute(ExecutorInput(...), sink, budget)
```

`sink.emit(kind, payload)` 由 `services/chat.py` 实现，负责持久化事件；执行器不持有 SSE 连接。

## 边界

- 不创建订单、不读取库存、不调用模型。
- 每个 token 前检查 cancel/deadline；工具失败抛错，由 ChatService 写 error 并标 failed。
- P03 用真实执行器替换 FakeAgent，保持 EventSink/ExecutionOutcome 协议。
