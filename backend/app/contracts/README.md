# contracts 共享契约

## 职责

P00/P01/P02 的跨层数据、请求/响应、事件和分页契约：

- `common.py`：Envelope、Meta、AppError、PageQuery、Page、RequestContext、Clock。
- `domain.py`：Part/Supplier/Quote/Inventory、历史草稿/订单、SourceRef、补货请求/预览、InventoryView/QuoteView/InventorySummary。
- `events.py`：12 类事件 EventEnvelope、RunView/ThreadView/MessageView/ConversationView、ChatRequest；payload 按事件类型校验。`MessageView.model_mode` 可为空，历史消息依所属 run 的 `run_started` 元数据标注；assistant `evidence` 保存最终数字结论的 call/record/fact 引用。
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
- assistant 模式未知时不推断；模型工具增量按供应商稳定 index 拼合，调用完成协议缺失视为协议错误。
- `order_workflow.py` 固定 P04 草稿准备/修改、审批恢复和订单工作流请求；OrderDraft 的库存版本及报价快照是排除在 P01 固定 seed schema 外的持久元数据。
- 金额使用整数分，数量严格为整数；订单创建请求只允许 draft_id、approval_id、idempotency_key。

## P04 验证

`uv run pytest tests/integration/test_drafts.py tests/integration/test_checkpoint_resume.py tests/integration/test_order_idempotency.py -q`；Schema 由 `uv run python -m scripts.export_contracts --check` 校验。
# API、事件与Harness契约

## 职责

- `events.py` 是REST/SSE与Mongo运行视图的版本化来源；`events-schema.v1.json`、`frontend/src/lib/events.ts`由`scripts.export_contracts`生成。
- `workflow.py` 定义P05任务类型、四阶段、计划条目、来源引用和评审检查。事件只追加结构字段，保留P04 interrupt与旧RunView默认值。
- phase与Run.status分开；`waiting_input`仍是未终结Run，phase保留executing。review仅存可展示的check id、失败原因与数据引用，不含模型私有推理。

## 示例

```json
{"phase":"reviewing","task_type":"inventory","revision_count":1}
```

计划步骤只有成功工具结果及可追溯SourceRef才允许标记done。确定性评审失败不能被语义评审覆盖。订单结果引用来自持久业务查询，评审不触发订单提交。

## 验证

```powershell
uv run pytest tests/unit/test_workflow_contracts.py tests/unit/test_plan_updates.py -q
uv run python -m scripts.export_contracts --check
```
