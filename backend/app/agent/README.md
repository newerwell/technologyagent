# agent 执行器、Harness、评审与订单恢复图（P03–P05）

## 职责

- `budget.py`：`RunBudget` 检查 cancel/活跃 deadline，向模型、MCP 发现与工具调用提供剩余时限，并对调用做原子计数（DB counter）。
- `graph.py`：P03只读工具图与P05外层Harness；工具调用先收齐，计划按成功事实更新，最终正文暂存到硬校验和语义评审通过后才发 `token`。
- `state.py`：`AgentStateV1` 增量字段兼容旧状态/checkpoint；Run.status仍由RunService维护。
- `harness.py`：任务分类、结构化计划、阶段机、来源驱动计划更新、phase/plan事件发布与签名去重；最多2次修订。
- P05补修：每个运行持久原始请求；查询计划用 `QueryEvidence`（工具、call_id、参数范围、时间与total）完成，空页不伪造实体；失败步骤可以在真实重试后转为done。累计活跃预算从Run持久字段继续计算，审批等待期间暂停。
- `review.py` / `rubrics.yaml`：确定性数值/范围/来源/计划/审批订单核查，再用无工具模型调用检查语义遗漏；模型结果只能增加失败，不能覆盖硬失败。
- `evidence.py`：保留 call_id、记录引用、字段/值/单位、实体范围与 as_of；按结构化 claim 校验正式回答中的字段、数值、单位和业务结论，校验通过前正文只缓冲不发布。
- `fact_checks.py`：P06-fix2共用字段校验；金额精确到分，数量/天数要求整数，答案字段按表头和相邻分句绑定，跨实体同值在未说明范围时判为歧义。重复呈现的同一业务范围事实合并，库存预警数、目标缺口和用户交期上限保留独立字段。
- `scripted_model.py`：fake/测试用 ScriptedModel 与明确标注的 DemoScriptedModel。
- `local_tools.py`：fake/离线测试使用同一业务 handler 的本地 registry；生产 live 走 MCP。
- `fake_executor.py`：保留 P02 FakeAgent 历史实现，不再由 bootstrap 生产装配。
- `tools/analysis.py`：P06 `analysis_execute`只接收当前registry成功只读结果派生的数据集，或经同owner/run校验的已登记产物；Docker执行和产物登记失败返回工具错误，不运行宿主shell。
- P04 `checkpoints.py`/`order_nodes.py`：稳定节点 prepare/supplement/approve/submit v1，以 `(thread_id, checkpoint_ns=run_id)` 保存 Mongo 持久检查点。

## 调用

```python
executor = GraphExecutor(model, registry_factory, model_mode="live")
outcome = await executor.execute(ExecutorInput(...), sink, budget)
```

## 边界

- 只读图只有 model/tools 两个节点；P04订单图维持原稳定节点名与Mongo checkpoint协议。P05不新增模型可调用的写工具。
- 模型工具参数按供应商 index 收齐后才 JSON/schema 校验；只有 `stop`/`tool_calls` 属正常结束，提前 EOF、`length`、`content_filter` 和错误结束均失败，部分正文/参数不会作为成功结果执行或发布。
- 结构化数值校验覆盖明确的数值/单位/字段/实体与工具事实，也检查缺货事实和最终库存结论是否矛盾；不声称替代 P05 全面的自然语言语义评审。
- 语义评审只接收筛选后的工具事实与白名单订单/operation/approval字段；日期时间数字不按库存数值校验。订单单号与数据库ID分别传递，避免把引用ID误判为对外单号。
- 模型 60s、读工具 15s、活跃 180s、模型 20 次、工具 30 次；失败调用也计数。
- 断线只关观察 SSE；ChatService 的任务继续写持久事件。
- waiting_input 持久化 interrupt，resume 校验 owner、同 run、interrupt_id 与草稿版本；编辑会 supersede 审批并回到确认节点。
- 图节点恢复可能重跑；订单写入只由 MutationService 在事务内执行，业务幂等不可省略。
- phase规划/执行/评审/结果与Run.status分开；等待审批保留executing + waiting_input。失败run即使phase=result，UI仍显示失败。
- P05每个候选回答最多评审3次、最多修订2次；模型调用计入同一RunBudget。硬事实失败会触发有限修订；不能发布未通过正文。
- 订单图完成后只用operation/order/approval集合查询已提交结果，再输出评审；评审和恢复代码不调用`submit_order_v1`或MutationService。
- 订单说明评审先做确定性订单/审批事实核对，硬失败不请求语义评审。通过后最多3次检查、2次纯正文修订；每次只读已核验订单事实，没有业务写工具。评审异常写入明确终态并保留订单引用。
- fake模式使用明确的ScriptedModel离线评审响应；不能作为真实语义或模型验收。

## 验证

`uv run pytest tests/unit/test_evidence.py tests/integration/test_agent_tools.py tests/integration/test_agent_stream.py -q`
`uv run pytest tests/integration/test_checkpoint_resume.py tests/integration/test_order_idempotency.py -q`
`uv run pytest tests/integration/test_harness.py tests/unit/test_phase_transitions.py tests/unit/test_plan_updates.py tests/unit/test_deterministic_review.py tests/unit/test_semantic_review.py -q`
