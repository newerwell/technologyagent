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
- P06-fix2任务范围：Harness从原始请求提取仓库、物料、交期上限和目标意图，随plan事件保留为`request_constraints`；交期筛选必须有匹配`max_lead_days`的`replenishment_preview`参数证据。目标缺口回答需有完整页集并逐项覆盖正缺口；`inventory_warning`只满足安全预警问题，不可替代目标缺口查询。
- P06-fix2补验收：供应商推荐/最便宜问题分类为`supplier`计划；带交期上限时保存筛选参数查询证据。`verified_answers.py`只在同范围查询完整、服务返回明确推荐报价或完整报价集合确认无有效报价时，按具名字段生成库存/报价事实核心，并标注来源和观察时间。布尔报价/预警事实按类型和实体核对。证据缺失、冲突或实体不明确时不生成正文，仍由硬评审拒绝；自由正文不能覆盖渲染核心事实。
- `scripted_model.py`：fake/测试用 ScriptedModel 与明确标注的 DemoScriptedModel。
- `local_tools.py`：fake/离线测试使用同一业务 handler 的本地 registry；生产 live 走 MCP。
- `fake_executor.py`：保留 P02 FakeAgent 历史实现，不再由 bootstrap 生产装配。
- `tools/analysis.py`：P06 `analysis_execute`只接收当前registry成功只读结果派生的数据集，或经同owner/run校验的已登记产物；Docker执行和产物登记失败返回工具错误，不运行宿主shell。
- P04 `checkpoints.py`/`order_nodes.py`：稳定节点 prepare/supplement/approve/submit v1，以 `(thread_id, checkpoint_ns=run_id)` 保存 Mongo 持久检查点。

## P07 版本路由、专家与技能

- `graph_versions.py`：旧run按持久 `graph_version` 继续走v1；新run固定v2。父run合并owner偏好与本轮约束后，按分析、订单查询、订单准备及否定范围路由；工具参数和评审使用同一有效范围。组合最多两次委派并传结构化分析证据，仍共用父run模型/工具/时限预算。
- `deepagent_adapter.py`：检查锁定的DeepAgents版本及工厂能力。锁定版默认带有项目禁止的内置工具，且不兼容当前ModelPort/事件/中断边界，因此本阶段选择具名LangGraph子图，不开启DeepAgents默认工具。
- `specialists/`：YAML列出目标、工具白名单、输入/输出JSON Schema及不递归/不自批规则；`RoleToolRegistry`在工具发现与调用时双重校验。
- `skill_loader.py`：只从仓库固定 `skills/` 根目录加载任务所需技能，返回版本、正文与示例SHA-256；run保存hash清单供追溯。
- `request_intent.py`：确定性区分明确记忆命令、本轮覆盖、分析、只读订单查询、订单准备和否定；纯订单不会制造空分析任务，查询不创建草稿。
- 组合请求明确要求报告文件时，analyst提示必须使用当前run只读查询数据调用 `artifact_report`；父路由以同run持久 `artifact_ready` 报告事件确认后才允许继续订单准备。只有文本摘要时以 `REPORT_ARTIFACT_REQUIRED` 失败，不会把未完成报告的组合任务推进到审批。
- `versions/v1.py`：固定旧v1状态schema、builder引用、订单节点名和checkpoint namespace ABI；v2适配变更不迁移旧审批。
- P07-fix1补验收：明确报告请求要求analyst调用`artifact_report`，并由父run核对同run持久`artifact_ready`；缺失时`REPORT_ARTIFACT_REQUIRED`阻断后续订单准备。P07最新offline为199 unit/181 integration/38 frontend；fake browser 12/12，下载API字节5/5。新P03 live 3×3为2/9；P07 live因模型未生成报告文件而失败，严格验收未关闭。
- 使用例：`route_executor(executor, request, sink, budget)`。`analysis_execute`只在v2 analyst actor可用；订单专家仍通过订单工作流和人工审批写入。

详细白名单、schema格式、错误和兼容限制见[专家模块说明](specialists/README.md)及[技能说明](../../../skills/README.md)。

验证：`uv run pytest tests/unit/test_p07_specialists_skills.py tests/integration/test_graph_upgrade.py tests/integration/test_specialists.py -q`。

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

P06-fix2补验收还验证了 `tests/unit/test_fact_checks.py`、`tests/unit/test_live_acceptance.py` 与 `tests/integration/test_readonly_scope_answers.py`。2026-10-25完整Windows P06 offline为9/9 checks（157 unit、160 integration、38 frontend）；fake browser为2/2 checks、Playwright 9/9；显式live批次 `20261025T050032Z` 的P03三题各3次共9/9，详情及每次DB快照见[证据](../../../evidence/P06-fix2.md)。这不等同于正式后端浏览器下载或所有报告格式的人工打开验收。
# P08 前置意图与独立事实验收补修

P08 前置修复按标点分句限制订单否定范围，供应商排除不会否决后续正向备单；“删除我的偏好”先于通用偏好查看解析。事实核验接受目录具体单位“对”并继续拒绝单位错配。P03 live oracle 对P001/P003/P004使用可信fixture单位套/个/条，且逐项核对工具事实与最终回答；静态回放通过不代表真实模型live已通过。

# P09-F02 跨来源事实身份

库存与补货预览的来源记录ID仅作为追溯信息；事实匹配按字段、物料、仓库、供应商/订单、指标和单位形成业务身份。同一业务事实由多个工具一致观察时合并为一个可引用事实；同一业务身份出现不同最新值仍报告冲突，不同物料/仓库/供应商、字段或单位继续保持独立并拒绝含糊主张。
