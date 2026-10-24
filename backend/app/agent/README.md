# agent 执行器与工具循环（P03）

## 职责

- `budget.py`：`RunBudget` 检查 cancel/活跃 deadline，并对模型/工具调用做原子计数（DB counter）。
- `graph.py`：LangGraph v1，model → tools → model；工具白名单只读，工具失败反馈模型，模型/工具超时与预算受限。
- `state.py`：`AgentStateV1` 的 P03 子集（messages/evidence/final/usage）。
- `evidence.py`：从成功 ToolResult 收集 SourceRef；禁止无依据数字和“已下单”结论。
- `scripted_model.py`：fake/测试用 ScriptedModel 与明确标注的 DemoScriptedModel。
- `local_tools.py`：fake/离线测试使用同一业务 handler 的本地 registry；生产 live 走 MCP。
- `fake_executor.py`：保留 P02 FakeAgent 历史实现，不再由 bootstrap 生产装配。

## 调用

```python
executor = GraphExecutor(model, registry_factory, model_mode="live")
outcome = await executor.execute(ExecutorInput(...), sink, budget)
```

## 边界

- 图只有 model/tools 两个节点；不实现订单写入、审批或专家。
- 模型工具参数收齐后 JSON/schema 校验，失败不执行，返回可解释 ToolResult。
- 模型 60s、读工具 15s、活跃 180s、模型 20 次、工具 30 次；失败调用也计数。
- 断线只关观察 SSE；ChatService 的任务继续写持久事件。
