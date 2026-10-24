# contracts 共享契约

## 职责

P00/P01/P02 的跨层数据、请求/响应、事件和分页契约：

- `common.py`：Envelope、Meta、AppError、PageQuery、Page、RequestContext、Clock。
- `domain.py`：Part/Supplier/Quote/Inventory、历史草稿/订单、SourceRef、补货请求/预览、InventoryView/QuoteView/InventorySummary。
- `events.py`：12 类事件 EventEnvelope、RunView/ThreadView/MessageView/ConversationView、ChatRequest；payload 按事件类型校验。
- `agent.py`：ExecutorInput/ExecutionOutcome；P03 再扩展工具/模型类型。
- `domain-schema.v1.json` / `events-schema.v1.json`：由脚本生成的稳定 JSON Schema。

## 生成

```powershell
uv run python -m scripts.export_contracts
uv run python -m scripts.export_contracts --check
```

生成目标同时包括 `frontend/src/lib/domain-types.ts`、`frontend/src/lib/events.ts`。不要手改生成文件；改 Pydantic 模型后重新生成并提交差异。

示例事件：

```python
EventEnvelope(type="token", event_id="evt_...", seq=2, thread_id="thr_...", run_id="run_...", at=clock.now(), payload={"message_id": "msg_...", "delta": "你好", "actor": "main"})
```

事件 `seq` 从 1 递增，`(run_id, seq)` 唯一；payload 非法会被 Pydantic 拒绝。

## 边界

- 金额字段一律整数分，币种固定 CNY。
- 时间使用带时区 datetime，JSON 输出 ISO 8601 UTC。
- 字段变更需要同步调用方、生成类型、夹具与测试；`--check` 防止静默漂移。
