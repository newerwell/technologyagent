# P03 补修与验收 Implementation Plan

> **For agentic workers:** 其他实施 Agent 按 executing-plans 逐项实施；独立任务可用 subagent-driven-development。当前规划聊天不改产品。只完成本阶段补修及可执行验收，不开始 P04。

**Goal:** 修复独立审查 R01–R09，关闭 P02-R02 剩余窗口，并让 P03 的真实模型验收可靠可执行。
**Architecture:** 保留 ModelPort、GraphExecutor、ToolRegistry 和持久事件外壳；增加完整流式调用状态、带字段的事实校验、视图/运行归属和严格验收证据。保持只读。
**Tech Stack:** 当前锁定 Python/FastAPI/LangGraph/PyMongo/FastMCP、Next.js/React/Vitest/Playwright；不借修复升级依赖。
**Spec:** [独立审查](../reviews/2026-10-24-P03-review.md)、[P03 spec](../specs/P03-agent-tools.md)、[原计划](./P03-implementation.md)、[共享契约](../specs/CONTRACTS.md)。

状态：待实施，输入 4efc643。P03 尚未完成 live 验收，phase-p03 尚不存在。补修实现可先提交上传，最终标签必须等必需验收完成。

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

- [ ] 先写实际 adapter→GraphExecutor 联合失败用例：一条工具调用参数分多块，name/id 仅首块；两条调用按 index 交错。断言每条恰好执行一次且完整参数返回模型。
- [ ] 贯穿供应商 raw.index 到应用契约，按同一调用合并 id/name/arguments；完整流结束后解析 JSON。支持空首片/尾片、Unicode、重复边界与非法最终 JSON，不能把每个 delta 当新调用。
- [ ] MockTransport 失败用例：一个 token 后 EOF、半个工具参数后 EOF；两者应明确失败。合法完成、合法工具结束、无 usage 保持通过；无敏感录制 fixtures 不访问供应商。
- [ ] 在 adapter 跟踪实际协议完成状态，提前 EOF 抛 MODEL_PROTOCOL_ERROR；图/ChatService 持久 failed/error/stream_end 并释放 thread，不能把部分文本当成功摘要。
- [ ] 跑 model_adapter、agent_tools、agent_stream 目标测试，保留失败前后证据后提交。

### P03-F02：把数量/金额绑定到工具事实（R02）

**Interfaces:** collect_evidence/ClaimCheck 形成明确事实结构，包含 call_id、entity/id、part/warehouse、字段、值、单位、scope/as_of；成功工具才可提供事实。现有 SourceRef 作为引用保留，不能只靠 refs 非空判通过。

- [ ] 失败用例：工具 shortage=55，声明999；预览66000分，声明999999分；无关 supplier 引用支持库存；P001/W01 事实用于 P002/W02。全部不能通过。
- [ ] 选择受控数值摘要渲染或显式结构化 claim→fact 映射，在文档固定具体输入输出与单位换算；金额保持整数分，展现660.00元不能被误判。不要依靠增加正则理解所有自然语言。
- [ ] 覆盖缺有效报价、过期报价、无记录、错误工具、跨 run 证据、相同字段不同实体；保留问候不查工具。对“不知道”的缺项如实说明，不能补造事实。
- [ ] 记录最终结论引用的 call_id/record 与事实范围，使持久结果/脱敏 trace 可审查；不能只让证据在临时 graph state 中存在却无法核对。
- [ ] 跑新 evidence 单测（当前需新增 tests/unit/test_evidence.py）与实际图集成，核对 P001 15/25/55、60500与66000，提交。

### P03-F03：校验后发布正式业务回答（R04）

**Interfaces:** EventSink 仍持久化后发送；正式 assistant 文本必须通过适用的结论约束。进度可沿用工具事件，保留 message_id 与恢复去重。

- [ ] 失败用例：模型“已下单，订单已创建”最终 failed 时，浏览器/持久 token 不能已将其作为正式回答发布；错误数量亦同。检查 sink 事件内容，不能只断言最终 status。
- [ ] 在图与 sink 之间设置明确的待校验正文缓冲/受控发布边界，业务结论通过后再发布；若保留中间文本，必须有独立语义和呈现，不能与最终业务结论混用。
- [ ] 保持正常安全回答可观察进度；刷新/重放后没有被拒绝的假下单结论，没有重复 assistant。工具步骤消息与最终答案职责说明写入模块 README。
- [ ] 跑 stream/history 与浏览器场景，确认模型断流/拒绝时终态及错误提示可恢复，再提交。

### P03-F04：总时限约束最后一次调用（R05）

**Interfaces:** RunBudget 暴露可测试的剩余时间或等价约束；有效等待上限为剩余总时限与单次时限的较小值。现有取消/DB 计数语义保持。

- [ ] 失败用例：注入时钟0→最后模型输出前181，应停止且不可 completed；179秒开始请求不得额外获得完整60秒；工具同理。
- [ ] 模型/工具/registry准备过程设置有界等待，调用后及最终成功前检查 active 和 cancel。错误区分总预算、模型超时、工具超时，不以清理耗时代替活跃时限判断。
- [ ] 补第21次模型/第31次工具不执行、失败也扣计数、取消后不调度、工具异常 tool_finished、清理执行的回归；时间用可注入时钟/短超时，不实等180秒。
- [ ] 运行 budget/agent/stream 相关测试，含实际 RunService 原子计数检查，提交。

### P03-F05：同视图连续运行的异步归属（R06，P02-R02）

**Interfaces:** useChat 外部 API 保持；view generation 与 run/发送操作归属分别可验证。新发送后旧 run 的 refresh/recover/callback 不能改 runId/status/messages/sending/error。

- [ ] 真实 hook deferred 失败用例：old stream_end→refreshAfterRun pending→send new→run_started new→old响应完成→new token；始终保持 new/running 并接收 token。
- [ ] 新发送时使旧运行操作失效，或增加严格 run epoch；所有异步成功/错误/finally 写回均核对所属视图和运行。不能只给首次 loadThread 加判断。
- [ ] 覆盖旧 recover pending、旧刷新 reject、续发认证失败可重试、切会话/newChat、旧 abort 不释放新锁；保留 P02-fix1 原测试。
- [ ] 真实浏览器延迟旧终态查询后连续发两轮，核对新文本、运行状态、停止目标；不要求真实供应商。跑 hooks/E2E 后提交。

### P03-F06：逐条保留历史模型模式（R08）

**Interfaces:** assistant 根据自身 runId 的持久 run/started 元数据展示模式；当前运行徽标与历史作者标签分开。必要历史字段保持旧数据兼容，未知值不能猜成 live。

- [ ] 实际组件失败用例：历史 live + 最新 fake，历史仍 Live Model；历史 fake + 最新 live，历史仍 ScriptedModel。当前空白页/当前运行徽标可用当前模式。
- [ ] 按每个消息 runId 合并可信模式，不能统一套 state.modelMode；如扩充 history API/DTO，更新契约、schema生成与调用方。旧P02记录可明确 FakeAgent/未知，不冒充供应商输出。
- [ ] 覆盖刷新、多轮、切换会话、老记录缺模式、恢复中后到数据；用无真实模型的固定历史 fixture 渲染验证。
- [ ] 跑组件/hook、类型/契约检查，提交。

### P03-F07：MCP 发现失败清理（R09）

**Interfaces:** McpRegistryFactory 负责未成功返回时关闭 client；成功后由 registry/executor 关闭，恰好一次。正常 token TTL 机制不变。

- [ ] 失败用例：客户端已连接，list_tools 抛错；断言 opened=closed=1。分别覆盖取消、连接半初始化和正常返回。
- [ ] 在工厂加入失败/取消清理，处理 _get_client 部分初始化；清理失败不能掩盖原始错误，不泄漏 Authorization。
- [ ] 模拟连接断开时图有界结束、释放 thread，连续失败无遗留客户端/后台任务；用实际 MCP 测试进程补异常路径证据。
- [ ] 跑 MCP 与 agent_stream 目标测试，提交。

### P03-F08：修复 live 验收与统一入口（R03）

**Interfaces:** verify_stage P03 live 在缺显式启用/配置时 exit2、not_run；具备条件后执行实际 live 测试并记录逐项退出/是否跳过。测试自身验证服务实际 model_mode=live；环境变量存在不能证明服务用了真模型。

- [ ] 先写验收器反例：fake模式、failed终态、仅有工具error而无成功事实、缺末事件、无工具或错误工具参数、无记录引用均不通过；9份弱字符串拼接不能再9/9。预算内纠错后有完整成功依据的运行可以验收，但保留全部失败/纠错轨迹。
- [ ] QUESTIONS 固定前三个问题各3次，检查 W01/P001缺55；7天S01/5天/55件/66000分；P003无有效报价且不编造。核对成功工具的参数/结果，并与独立测试库固定seed事实对照，不能只搜数字子串。
- [ ] trace 记录全部尝试、request/run/call_id、实际模式/模型名、开始结束时间、工具参数/成功结果/来源记录/事实对照/终态/原因；Key/header不落盘，原轨迹仅.runtime；evidence记摘要和实际通过率。
- [ ] 接入非空 P03 live manifest；不把全skip的pytest exit0当通过。缺Key继续明确not_run，不为消除skip强行写假Key或调用未知模型。
- [ ] 无Key时用受控传输/假的验收响应验证“验收器会拒绝假通过”，明确它不是live。若用户已在本机配置真实模型并显式启用，才执行真实9次；失败保留全部尝试，不能只记录成功重试。
- [ ] 跑验收器单测/manifest边界；更新 scripts/live README 的准确前提、服务模式与启动方式，提交。

### P03-F09：回归、证据与远程交付

- [ ] 跑 `uv run python -m scripts.verify_stage P03 --mode offline --report .runtime/reports/P03-fix1-offline.json`，确认最终退出码与实际数量，含P00–P02回归和F01–F08新增断言。
- [ ] 独立测试库启动服务，执行 P03 browser manifest；新增连续run/逐消息模式证据。停止本次服务、清理独立库，原有未跟踪文件保留。
- [ ] 更新 evidence/P03-fix1.md、模块README、STATUS、P03 spec/plan、实施入口；分别写 implemented/offline/browser/live，不把此计划勾选当完成。
- [ ] 显式暂存补修路径，commit、push origin/main、核对远程SHA与本次实现CI；不强推，不移动 phase-p02-fix1 等旧标签。
- [ ] 无Key：上传可审查补修并保持P03未完整验收，报告live缺条件，停止；**不创建phase-p03、不开始P04**。有条件且真实9次必需验收通过：最终记录提交后创建annotated phase-p03，推送并核对解引用SHA，再交回规划者复核。

## 给实施 Agent 的提示词

```text
只完成 TechnologyAgent 当前 P03 补修及验收，不开始 P04。先确认仓库实际绝对路径、Git状态、origin/main和phase-p02-fix1。读AGENTS.md、docs/reviews/2026-10-24-P03-review.md、docs/implementation/P03-followup.md、原P03 spec/plan、共享契约和STATUS。
按F01–F09修复R01–R09，包括真实工具参数分片、结构化事实数值校验、正式正文校验后发布、总时限、P02-R02同视图旧刷新窗口、提前EOF、历史模式归属、MCP失败清理、live验收假通过和空manifest。每项先保留确定性失败用例，不只跑原happy path。
保持9项只读工具和原目录/协议边界，不写订单，不reset开发库。完成offline/browser与新增断言，更新模块说明和evidence/P03-fix1.md，显式commit/push并核对CI/远程SHA。
无Key时如实live not_run，补修实现可以上传，但不得创建phase-p03或开始P04。真实模型配置与显式启用齐备后才跑固定3问题各3次，记录全部轨迹和DB对照；所有必需验收通过后才创建并核对phase-p03。原标签不动，保留无关未跟踪文件。交付后停止并等待复核。
```
