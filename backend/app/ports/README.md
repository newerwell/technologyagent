# ports 外部能力接口

## 职责

用 Protocol 定义应用可替换能力，services/domain 不直接依赖 MongoDB或Docker：

- `CatalogReader`：search/get/list parts、suppliers、quotes，以及 `page_quotes`。
- `InventoryReader`：分页、详情、`list_scope(part_ids, warehouse_id)`、全量 `list_all`。
- `executor.py`：`EventSink.emit(kind,payload)` 与 `AgentExecutor.execute(ExecutorInput,sink,budget)`；执行器只通过 sink 持久化事件，不持有 SSE 连接。
- `model.py`：`ModelPort.stream(messages,tools,ctx)` 输出归一化 token/tool_call/usage。
- `tools.py`：`ToolSpec`/`ToolResult`/`ToolRegistry`；工具 schema 不暴露 owner/run。
- `artifacts.py`：ArtifactPort登记已校验输出与按当前owner读取产物。
- `sandbox.py`：SandboxPort执行资源受限的SandboxJob并返回SandboxResult；能力探测不替代每次容器inspect。

## 实现与接入

- P01 实现：`repositories/catalog.py`、`repositories/inventory.py`。
- P02 实现：`agent/fake_executor.py` 实现 AgentExecutor；`services/chat.py` 提供 EventSink 与任务管理。
- P03 实现：`agent/graph.py` 实现 AgentExecutor；`integrations/model.py` 实现 ModelPort；`integrations/mcp.py` / `agent/local_tools.py` 实现 ToolRegistry。
- P06 实现：`services/artifacts.py` 实现 ArtifactPort；`sandbox/runner.py` 实现 SandboxPort。
- 装配：`bootstrap.build_container` 注入到 `CatalogService` / `InventoryService` / `ReplenishmentService` / `RunService` / `ChatService`。
- P08 可通过 Provider 增加 ERP 实现，不复制补货规则。
- P07 `PreferenceStore`（`ports/preferences.py`）按owner管理显式偏好：list、remember、delete。Mongo适配器由`PreferenceRepository`实现，HTTP调用由`PreferenceService`校验白名单与业务引用。

## 边界

- 不返回自然语言，不计算补货公式。
- 分页必须把 total 基于完整 filter 计算，不能把单页当全量。
- `list_scope` 返回全部指定 part/warehouse，preview 不依赖首页。
- ArtifactPort按artifact_id和owner授权，不接受宿主路径；SandboxPort失败不回退宿主执行。
