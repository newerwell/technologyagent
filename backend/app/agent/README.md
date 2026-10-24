# agent 执行器、工具循环与订单恢复图（P03/P04）

## 职责

- `budget.py`：`RunBudget` 检查 cancel/活跃 deadline，向模型、MCP 发现与工具调用提供剩余时限，并对调用做原子计数（DB counter）。
- `graph.py`：LangGraph v1，按工具调用索引拼合增量；只读白名单、工具错误反馈、总时限约束；正文先缓冲，事实校验通过后才发 `token`。
- `state.py`：`AgentStateV1` 的 P03 子集（messages/evidence/final/usage）。
- `evidence.py`：保留 call_id、记录引用、字段/值/单位、实体范围与 as_of；数量/金额必须匹配成功工具事实，不能只靠引用非空。
- `scripted_model.py`：fake/测试用 ScriptedModel 与明确标注的 DemoScriptedModel。
- `local_tools.py`：fake/离线测试使用同一业务 handler 的本地 registry；生产 live 走 MCP。
- `fake_executor.py`：保留 P02 FakeAgent 历史实现，不再由 bootstrap 生产装配。
- P04 `checkpoints.py`/`order_nodes.py`：稳定节点 prepare/supplement/approve/submit v1，以 `(thread_id, checkpoint_ns=run_id)` 保存 Mongo 持久检查点。

## 调用

```python
executor = GraphExecutor(model, registry_factory, model_mode="live")
outcome = await executor.execute(ExecutorInput(...), sink, budget)
```

## 边界

- 图只有 model/tools 两个节点；不实现订单写入、审批或专家。
- 模型工具参数按供应商 index 收齐后才 JSON/schema 校验；无合法终止标记的流失败，部分正文/参数不会作为成功结果执行或发布。
- 结构化数值校验覆盖明确的数值/单位/实体与工具事实；不声称替代 P05 全面的自然语言语义评审。
- 模型 60s、读工具 15s、活跃 180s、模型 20 次、工具 30 次；失败调用也计数。
- 断线只关观察 SSE；ChatService 的任务继续写持久事件。
- waiting_input 持久化 interrupt，resume 校验 owner、同 run、interrupt_id 与草稿版本；编辑会 supersede 审批并回到确认节点。
- 图节点恢复可能重跑；订单写入只由 MutationService 在事务内执行，业务幂等不可省略。

## 验证

`uv run pytest tests/unit/test_evidence.py tests/integration/test_agent_tools.py tests/integration/test_agent_stream.py -q`
`uv run pytest tests/integration/test_checkpoint_resume.py tests/integration/test_order_idempotency.py -q`
