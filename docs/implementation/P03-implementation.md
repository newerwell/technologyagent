# P03 真实模型与MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans if available; otherwise follow the task checklist directly. Implement only this stage.

**Goal:** 单Agent通过MCP读取本地业务并回答有来源的问题，替换FakeAgent而不重写UI。
**Architecture:** ModelPort输出token/tool_call，图驱动受控ToolRegistry，MCP工具调用同一业务服务。
**Tech Stack:** P00锁定LangGraph、模型适配、FastMCP与客户端；不默认依赖DeepAgents。
**Spec:** [P03](../specs/P03-agent-tools.md)、[接口映射](./INTERFACES.md)第4节。

**独立复核（2026-10-24）：** 原实现基础回归通过，审查发现9项缺口。P03-fix1 已按 [补修计划](./P03-followup.md) 实施并完成新增确定性测试；offline/browser/CI 结果见 [evidence/P03-fix1.md](../../evidence/P03-fix1.md)。本次下方 T01–T05 勾选记录基础实现，不能单独替代补修证据。真实模型 3×3 验收仍是 P03-A06 必需条件；缺Key时不创建phase-p03、不开始P04。

P03-fix1 的关键补充：供应商 `tool_call.index` 稳定合并且流必须合法结束；数值与成功工具返回的事实/范围/单位校验并持久化引用；最终正文先校验后发布；每次调用 timeout 受 180 秒 run deadline 限制；MCP 建立/发现失败由工厂清理。Live验收器需模式、成功终态、成功只读调用、参数、结果事实和数据库对照同时成立。

## Global Constraints

仅9项首批只读工具；模型最多20次、工具30次，超时按共享契约；owner/run来自可信上下文；无Key时不假装live；不创建订单。

## Review Focus

模型流式tool参数不完整→T01；MCP会话身份串扰→T02；循环/超时→T03；数据无来源→T05；mock通过替代live→T06。

### P03-T01：模型端口与适配

**Files:** Create `ports/model.py`、`integrations/model.py`、`agent/scripted_model.py`；Extend contracts/agent；Test `tests/unit/test_model_adapter.py`。
**Interfaces:** ModelPort.stream、ModelMessage/ModelDelta；scripted模型按固定输入输出模拟tool call，真实适配只做供应商协议转换。

- [x] 用录制的无敏感协议fixture测试token、tool_call增量拼接、无usage、供应商错误和请求超时；不能把半个JSON立即调工具。
- [x] 实现MODEL_MODE切换；tool args收齐后JSON解析和schema校验，失败返回结构化错误进入有限修正，不execute任意文本。
- [x] 真模型Key仅后端读取；usage未知时记录null而非0；日志脱敏。
- [x] 跑适配器单元测试；最小live请求单独启用并记录模型名、时间、结果，不预先宣称业务成功。

### P03-T02：MCP工具和可信上下文

**Files:** Create `mcp_server/{__init__,server}.py`、`mcp_server/tools/{catalog,inventory}.py`、`integrations/mcp.py`、`ports/tools.py`；Extend services/sessions；Test `tests/integration/test_mcp_tools.py`。
**Interfaces:** 首批inventory_page/warning/get、supplier_query/get、part_search/query、quote_list、replenishment_preview；ToolSpec不暴露owner参数。

- [x] 写list_tools名称/schema断言和真实call_tool测试，P001数值与HTTP一致；无效session拒绝，ownerA/B并发header不串。
- [x] 单独Streamable HTTP进程从相同bootstrap装配业务服务；每run短期opaque token只授权对应owner/run/actor，调用上下文由MCP服务端解析。
- [x] MCP参数转换后调用P01服务，不访问隐藏远程ERP。工具返回Envelope和source；名字/参数/结果统一由Registry描述生成。
- [x] 执行`uv run pytest tests/integration/test_mcp_tools.py -q`；关闭服务后ready报告MCP不可用，不能悄悄只剩空聊天。

### P03-T03：图、预算与工具循环

**Files:** Create `agent/{graph,state,tool_registry,budget}.py`；Extend contracts/agent、RunService；Test `tests/integration/test_agent_tools.py`。
**Interfaces:** build_graph_v1依赖ModelPort/ToolRegistry；GraphExecutor实现AgentExecutor；Run保存graph_version=v1。

- [x] scripted模型先发inventory/quote工具调用再回答；断言实际工具调用、结果返回模型、最后run完成；禁用未知或写工具。
- [x] 图只做model→tools→model，工具失败作为真实ToolResult反馈；不把工具内容当新系统指令。取消检查放在模型/工具调用前后。
- [x] RunBudget用DB原子计数，失败调用也扣；模型60秒、读工具15秒、活跃180秒；超预算发明确error，停止生成成功结论。
- [x] 循环scripted模型验证第21次模型和31次工具不执行；工具耗时与总预算用可注入时钟测试，避免实等180秒。

### P03-T04：真实事件映射到现有UI

**Files:** Modify services/chat、bootstrap、前端工具卡片；Create `tests/integration/test_agent_stream.py`。
**Interfaces:** 保留P02事件封装及同message_id，actor=main，工具call_id贯穿start/finish/trace。

- [x] 把图的真实token/tool调用映射到EventSink，模型adapter不直接给浏览器写SSE。
- [x] 每个tool_started都有tool_finished(success/error)，参数摘要由服务端脱敏；正常问候不强制查工具，业务数值必须有依据。
- [x] 工具异常、模型断流能正确结束run并释放thread；重放/历史仍走P02协议。
- [x] 跑stream测试及P02事件/解析回归，页面不再把live结果标模拟，fake模式仍明确展示。

### P03-T05：数据证据与结论约束

**Files:** Create `agent/evidence.py`、`tests/unit/test_evidence.py`；Extend状态和回答摘要。
**Interfaces:** `collect_evidence(tool_result)->list[SourceRef]`；`validate_business_claims(answer,evidence)->ClaimCheck`不靠字符串猜所有语义。

- [x] 业务工具输出结构化数值及record引用，图状态保留call_id/entity/id/as_of/scope；格式化摘要直接引用PreviewResult金额而非模型重算。
- [x] 无报价、未知记录、过期数据分别标明确缺项。对结构化金额/数量与工具依据做硬校验；自然语言表达仍需后续P05语义检查，不能宣称此时覆盖所有幻觉。
- [x] 跨会话不复制上个run的evidence；错误response不能当有效SourceRef。
- [x] 跑evidence测试，检查无工具支持的“已下单”结论被只读版本禁止。

### P03-T06：离线和真实模型分开验收

**Files:** Create `tests/live/test_readonly_agent.py`、`evidence/P03.md`；Update验证manifest及README。
**Interfaces:** live测试显式参数/环境启用，脱敏trace输出到.runtime，evidence只记录摘要。

- [x] 离线验证工具链、错误/超时、并发身份、预算；所有实际DB结果用固定seed核对。
- [ ] 三个spec问题各跑3次，共9次；期望P001缺55、7天选S01/660元、P003无有效报价；记录全部尝试、实际通过率和工具轨迹。
- [x] 没Key只能交付“实现/离线验证，真实模型not_run”，不能勾选要求live通过的阶段最终验收；报告缺失条件，保留当前阶段。
- [ ] 必需条件满足后按Git规则上传`phase-p03`，不继续写P04订单。
