# ports 外部能力接口

## 职责

用 Protocol 定义 P01/P02 能力，services/domain 不直接依赖 MongoDB：

- `CatalogReader`：search/get/list parts、suppliers、quotes，以及 `page_quotes`。
- `InventoryReader`：分页、详情、`list_scope(part_ids, warehouse_id)`、全量 `list_all`。
- `executor.py`：`EventSink.emit(kind,payload)` 与 `AgentExecutor.execute(ExecutorInput,sink,budget)`；执行器只通过 sink 持久化事件，不持有 SSE 连接。

## 实现与接入

- P01 实现：`repositories/catalog.py`、`repositories/inventory.py`。
- P02 实现：`agent/fake_executor.py` 实现 AgentExecutor；`services/chat.py` 提供 EventSink 与任务管理。
- 装配：`bootstrap.build_container` 注入到 `CatalogService` / `InventoryService` / `ReplenishmentService` / `RunService` / `ChatService`。
- P08 可通过 Provider 增加 ERP 实现，不复制补货规则。

## 边界

- 不返回自然语言，不计算补货公式。
- 分页必须把 total 基于完整 filter 计算，不能把单页当全量。
- `list_scope` 返回全部指定 part/warehouse，preview 不依赖首页。
