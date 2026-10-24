# P03 补修与验收 Implementation Plan

> **For agentic workers:** 其他实施 Agent 按 executing-plans 逐项实施；独立任务可用 subagent-driven-development。当前规划聊天不改产品。只完成本阶段补修及可执行验收，不开始 P04。

**Goal:** 修复独立审查 R01–R09，关闭 P02-R02 剩余窗口，并让 P03 的真实模型验收可靠可执行。
**Architecture:** 保留 ModelPort、GraphExecutor、ToolRegistry 和持久事件外壳；增加完整流式调用状态、带字段的事实校验、视图/运行归属和严格验收证据。保持只读。
**Tech Stack:** 当前锁定 Python/FastAPI/LangGraph/PyMongo/FastMCP、Next.js/React/Vitest/Playwright；不借修复升级依赖。
**Spec:** [独立审查](../reviews/2026-10-24-P03-review.md)、[P03 spec](../specs/P03-agent-tools.md)、[原计划](./P03-implementation.md)、[共享契约](../specs/CONTRACTS.md)。

状态：补修已实现；输入基线 `05e66c4638a3311beeddf02032c3439cbc728453`。offline/browser 验收通过；live 因真实模型凭据和显式启用缺失为 `not_run`，因此 P03 尚未完成最终验收、`phase-p03` 不存在。补修可交付复核，不开始 P04。结果见 [evidence/P03-fix1.md](../../evidence/P03-fix1.md)。

## Global Constraints

- 9 项只读工具；不增加订单写、审批、专家、沙箱或 ERP 功能。
- owner/run 来自可信上下文；每 run 独立客户端；模型 20 次/工具 30 次，模型 60 秒/读工具 15 秒/活跃 180 秒，失败调用扣预算。
- 不把脚本模型、MockTransport、skip、空 manifest 或 UI 测试标成真实模型通过。
- 原 phase-p00 至 phase-p02-fix1 标签不移动；phase-p03 只在包括 9 次 live 的必需条件满足后创建。
- 测试库前缀 technologyagent_test_*；不 reset 开发库；保留 .dsh-meow、现有 frontend/AGENTS.md 与无关改动；不提交密钥/原始轨迹。

## Review Focus

分片/交错调用和截断协议→F01；无关来源与错误数值→F02；拒绝前泄露业务结论→F03；最后请求越过总预算→F04；同视图续发旧刷新→F05；跨模式历史→F06；发现失败资源清理→F07；假模型/失败结果/skip 被算 live 通过→F08；实际交付证据→F09。

## 文件与接口分工

| 路径 | 本次职责 |
|---|---|
| contracts/agent.py、ports/model.py、integrations/model.py、agent/graph.py | 稳定调用 index/id、增量拼接、合法结束和错误传播 |
| agent/evidence.py、agent/state.py、contracts/agent.py、graph.py | 事实字段、范围和单位、结论验证与受控发布 |
| agent/budget.py、graph.py、必要 services/chat.py | 剩余活跃时限、成功前检查、保留 DB 次数上限 |
| frontend hooks/useChat.ts、lib/event-reducer.ts、MessageList.tsx | 运行操作归属与每条消息的模式；必要历史 API/生成类型同步修改 |
| integrations/mcp.py | 工厂失败/取消关闭与成功后的所有权交接 |
| scripts/verify_stage.py、tests/live/test_readonly_agent.py | 显式真实验收、严格拒绝假通过、事实对照与脱敏轨迹 |
| tests/unit、tests/integration、frontend hook/组件 tests、tests/e2e | 每项确定性失败用例、相称真实 DB/浏览器回归 |
| evidence/P03-fix1.md（新增）、STATUS、spec/plan/模块 README | 正确区分实现、离线、浏览器、真实模型与远程状态 |

上表 backend 路径均在 backend/app/ 下。新增事实/历史字段先更新契约及所有消费者，保留旧事件/历史读取兼容；不手写漂移的生成类型。

### P03-F01：完整工具增量与协议结束（R01/R07）

**Interfaces:** ModelDelta/ModelToolCall 保留稳定调用索引或等价标识；ModelPort.stream 仍产增量。明确供应商支持的结束条件；不完整调用不得执行，提前 EOF 不得 completed。

- [x] adapter→GraphExecutor 确定性失败用例覆盖参数分片、name/id 首片、index 交错，并断言每次工具恰执行一次且参数完整。
- [x] 供应商 raw.index 贯穿应用契约，合并 id/name/arguments 后解析 JSON；覆盖截断/非法最终 JSON与合法结束。
- [x] MockTransport 覆盖 token/半截工具参数提前 EOF；两者明确报 `MODEL_PROTOCOL_ERROR`；合法结束及无 usage 保持通过。
- [x] 图与 ChatService 将提前 EOF 持久化为 failed/error/stream_end，不发布部分文本为正式答案。
- [x] 定向测试：model adapter、agent tools、agent stream；全量 offline 报告在 evidence 中。

### P03-F02：把数量/金额绑定到工具事实（R02）

**Interfaces:** collect_evidence/ClaimCheck 形成明确事实结构，包含 call_id、entity/id、part/warehouse、字段、值、单位、scope/as_of；成功工具才可提供事实。现有 SourceRef 作为引用保留，不能只靠 refs 非空判通过。

- [x] 确定性反例拒绝错误 shortage/金额、无关 supplier、跨实体/范围事实；覆盖缺报价/过期/无记录/错误工具/跨 run。
- [x] 结构化事实按字段、实体、范围、值、单位、as_of 校验；分以整数分保存，正确将 66000 分与 660.00 元匹配。
- [x] 缺项不补造；无工具问候保持可用；只从成功工具结果采证。
- [x] 最终结论持久化 call_id/record/事实范围并进入脱敏 trace。
- [x] `tests/unit/test_evidence.py` 和实际图集成通过，覆盖 P001 15/25/55 与 60500/66000。

### P03-F03：校验后发布正式业务回答（R04）

**Interfaces:** EventSink 仍持久化后发送；正式 assistant 文本必须通过适用的结论约束。进度可沿用工具事件，保留 message_id 与恢复去重。

- [x] 确定性失败用例断言错误数量/假下单正文未出现在持久 token/sink 中。
- [x] 图先缓冲正文，校验通过后才作为正式 assistant 正文发布。
- [x] 模块 README 区分工具步骤消息和最终回答；重放/历史复用持久正文。
- [x] stream/history 与浏览器回归通过；提前 EOF/拒绝以失败终态呈现。

### P03-F04：总时限约束最后一次调用（R05）

**Interfaces:** RunBudget 暴露可测试的剩余时间或等价约束；有效等待上限为剩余总时限与单次时限的较小值。现有取消/DB 计数语义保持。

- [x] 注入时钟反例覆盖最后模型输出超过180秒以及剩余时限短于单次上限时的裁剪；工具同样受限。
- [x] 模型/工具/registry 准备与执行受剩余总时限约束；调用后及成功前检查 active/cancel。
- [x] 保留第21次模型/第31次工具限额、失败扣次、取消不调度及工具异常完成事件回归。
- [x] budget/agent/stream 与 RunService 原子计数检查通过。

### P03-F05：同视图连续运行的异步归属（R06，P02-R02）

**Interfaces:** useChat 外部 API 保持；view generation 与 run/发送操作归属分别可验证。新发送后旧 run 的 refresh/recover/callback 不能改 runId/status/messages/sending/error。

- [x] hook deferred 用例复现同视图旧终态 refresh pending 时启动新 run，旧响应回来不能改写新 run 状态/消息。
- [x] 新发送后旧运行操作失效；异步成功/错误/finally 写回受视图与运行归属约束。
- [x] 恢复、刷新失败、认证重试、切会话/newChat、旧 abort 锁回归与 P02-fix1 既有用例保留并通过。
- [x] 浏览器延迟旧终态查询后连续发送两轮通过；见 7/7 E2E manifest。

### P03-F06：逐条保留历史模型模式（R08）

**Interfaces:** assistant 根据自身 runId 的持久 run/started 元数据展示模式；当前运行徽标与历史作者标签分开。必要历史字段保持旧数据兼容，未知值不能猜成 live。

- [x] 组件 fixture 覆盖 live/fake 多轮历史标签分别按各自 run 显示。
- [x] 按消息关联的 run_started 元数据合并模式；旧记录未知时不猜测为 live；事件 schema 与调用方同步。
- [x] 刷新/历史和恢复后的逐条模式由 reducer/组件测试覆盖，不依赖真实模型。
- [x] 组件/hook、类型检查、契约检查通过。

### P03-F07：MCP 发现失败清理（R09）

**Interfaces:** McpRegistryFactory 负责未成功返回时关闭 client；成功后由 registry/executor 关闭，恰好一次。正常 token TTL 机制不变。

- [x] 失败用例覆盖已连接后发现失败、取消、半初始化和正常返回；验证恰好一次关闭。
- [x] 工厂失败/取消时清理部分资源，清理异常不覆盖原始错误。
- [x] 失败后不把所有权从工厂交出；成功时由 registry/executor 关闭。
- [x] MCP 清理与 agent_stream 目标测试通过。

### P03-F08：修复 live 验收与统一入口（R03）

**Interfaces:** verify_stage P03 live 在缺显式启用/配置时 exit2、not_run；具备条件后执行实际 live 测试并记录逐项退出/是否跳过。测试自身验证服务实际 model_mode=live；环境变量存在不能证明服务用了真模型。

- [x] 验收器反例覆盖 fake、failed、缺末事件、工具错误/缺失/参数不符/无记录等假成功；保留可追溯纠错轨迹。
- [x] 固定 QUESTIONS 为 3 个问题各 3 次，验收成功工具参数、结果与隔离 seed 事实，不以数字子串判断。
- [x] trace 实现记录 request/run/call_id、模式/模型、时间、参数/结果/事实/终态和原因并脱敏；原始轨迹限定 `.runtime`。
- [x] P03 live manifest 非空；全 skip 会失败，缺配置返回 `not_run` / exit 2。
- [x] fake/受控结果只用于验收器拒绝假通过的确定性测试；本次未运行真实 9 次，因为缺少真实配置与显式启用。
- [x] 验收器单测/manifest 边界通过；`scripts/README.md` 更新真实模型前置条件与轨迹策略。

### P03-F09：回归、证据与远程交付

- [x] P03 offline manifest exit 0、9/9，含 P00–P02 回归及新增断言；实际数量见 evidence。
- [x] 独立测试库启动服务，browser manifest exit 0、Playwright 7/7；停止本次服务并确认专用库不存在，保留无关未跟踪文件。
- [x] 更新 evidence、模块 README、STATUS、P03 spec/plan、实施入口；分开记录 implemented/offline/browser/live。
- [ ] 显式暂存补修路径，commit、push origin/main、核对远程SHA与本次实现CI；不强推，不移动 phase-p02-fix1 等旧标签。
- [ ] 无Key：上传可审查补修并保持P03未完整验收，报告live缺条件，停止；**不创建phase-p03、不开始P04**。有条件且真实9次必需验收通过：最终记录提交后创建annotated phase-p03，推送并核对解引用SHA，再交回规划者复核。

## 给实施 Agent 的提示词

```text
只完成 TechnologyAgent 当前 P03 补修及验收，不开始 P04。先确认仓库实际绝对路径、Git状态、origin/main和phase-p02-fix1。读AGENTS.md、docs/reviews/2026-10-24-P03-review.md、docs/implementation/P03-followup.md、原P03 spec/plan、共享契约和STATUS。
按F01–F09修复R01–R09，包括真实工具参数分片、结构化事实数值校验、正式正文校验后发布、总时限、P02-R02同视图旧刷新窗口、提前EOF、历史模式归属、MCP失败清理、live验收假通过和空manifest。每项先保留确定性失败用例，不只跑原happy path。
保持9项只读工具和原目录/协议边界，不写订单，不reset开发库。完成offline/browser与新增断言，更新模块说明和evidence/P03-fix1.md，显式commit/push并核对CI/远程SHA。
无Key时如实live not_run，补修实现可以上传，但不得创建phase-p03或开始P04。真实模型配置与显式启用齐备后才跑固定3问题各3次，记录全部轨迹和DB对照；所有必需验收通过后才创建并核对phase-p03。原标签不动，保留无关未跟踪文件。交付后停止并等待复核。
```
