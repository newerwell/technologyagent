# contracts 共享契约

## 职责

P00/P01/P02 的跨层数据、请求/响应、事件和分页契约：

- `common.py`：Envelope、Meta、AppError、PageQuery、Page、RequestContext、Clock。
- `domain.py`：Part/Supplier/Quote/Inventory、历史草稿/订单、SourceRef、补货请求/预览、InventoryView/QuoteView/InventorySummary。
- `events.py`：12 类事件 EventEnvelope、RunView/ThreadView/MessageView/ConversationView、ChatRequest；payload 按事件类型校验。`MessageView.model_mode` 可为空，历史消息依所属 run 的 `run_started` 元数据标注；assistant `evidence` 保存最终数字结论的 call/record/fact 引用。
- `agent.py`：ExecutorInput/ExecutionOutcome；P03/P05 增加模型、工具、计划和评审契约。
- `artifacts.py`：P06产物元数据/已收集输出、沙箱输入作业/结果、图表和报告 DTO；金额以整数分传递。
- `ArtifactListItem`：owner授权后的会话历史展示DTO，包含run_id、来源、文件名和不透明下载/预览URL，不包含宿主storage_key；`AuthorizedDataset`保留run、源调用、查询参数、时间和source_refs。
- `events.py`：P06 `artifact_ready` 追加 mime/source_refs 可选字段，保留v1兼容。
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

## P04/P06 验证

`uv run pytest tests/integration/test_drafts.py tests/integration/test_checkpoint_resume.py tests/integration/test_order_idempotency.py -q`；P06 DTO与事件Schema由P06 offline manifest及 `uv run python -m scripts.export_contracts --check` 校验。

## P08业务操作契约

通用提案由`ApprovalService`保存owner/run/action/payload_hash/version/source_refs，决定通过浏览器owner会话记录；模型不能自批。采购收货的receipt_id作用域为`(owner_id,provider,receipt_id)`，库存流水同时具有operation行唯一键和receipt作用域唯一键。入库/出库数量使用正整数，订单版本为expected_version；ERP金额从十进制元精确转换成整数分。真实ERP未验证字段不会出现在静态domain schema，未知字段由ERP适配器以missing_fields保留。
# API、事件与Harness契约

## 职责

- `events.py` 是REST/SSE与Mongo运行视图的版本化来源；`events-schema.v1.json`、`frontend/src/lib/events.ts`由`scripts.export_contracts`生成。
- `workflow.py` 定义P05任务类型、四阶段、计划条目、实体来源与查询级依据（call_id、工具、参数范围、时间和total）。空查询可完成查询步骤但不能提供数字事实。事件只追加结构字段，保留P04 interrupt与旧RunView默认值。
- `RunFinishedPayload` / `RunView`提供summary与committed_facts，区分订单已提交但说明评审失败；旧文档缺字段时用安全默认值。
- phase与Run.status分开；`waiting_input`仍是未终结Run，phase保留executing。review仅存可展示的check id、失败原因与数据引用，不含模型私有推理。
- P07 `delegation.py`以严格Pydantic模型定义owner/run/task/scope/evidence/preferences与专家返回；可信owner/run从服务上下文注入，证据值可保留数字、布尔或文本类型。RunView携带持久graph_version、技能hash和专家调用trace。
- Run缺少graph_version时兼容路由到v1；新run写v2。升级不迁移旧LangGraph checkpoint，不改变v1节点名/namespace。

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
# 收货事实规范化

`receipts.py` 的 `canonicalize_receipt()` 是收货准备/批准/事务执行共用入口。它严格拒绝布尔数量、空实体和额外字段，合并重复物料并按 part_id 排序；审批 hash、Receipt 文档、库存 Movement 与重放比较都基于相同规范事实。

`mutations.py` 的 `parse_mutation_payload(action, payload)` 为23业务工具对应的写动作提供按动作严格 schema；提案入库前与历史提案执行前都调用，未知字段、错类型、非正数量和旧坏记录均在生成 operation 或业务写之前拒绝。
