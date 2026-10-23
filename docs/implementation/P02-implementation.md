# P02 对话与事件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans if available; otherwise follow the task checklist directly. Implement only this stage.

**Goal:** 对话、历史、持久事件、刷新恢复和取消；当前执行器明确为FakeAgent。
**Architecture:** 后台执行任务写事件，SSE连接只观察已持久化事件；run和页面连接解耦。
**Tech Stack:** 既有FastAPI/Mongo/React；Vitest/Playwright。
**Spec:** [P02](../specs/P02-chat-streaming.md)、[接口映射](./INTERFACES.md)第3节。

## Global Constraints

每run seq从1递增；先持久化再发送；thread只有一个活跃run；同request_id去重；断线不自动cancel；P02未具备检查点，进程重启的孤儿run必须明确失败。

## Review Focus

并发run认领→T02；序号与最终消息原子性→T02；分块中文→T05；断线/取消差异→T03/T04；跨用户/重放重复→T04/T06。

### P02-T01：事件协议与生成类型

**Files:** Create `contracts/events.py`、`contracts/agent.py`、`ports/executor.py`、`agent/budget.py`、`tests/unit/test_event_contracts.py`、`fixtures/events/v1.json`；Modify export_contracts；Generate frontend/lib/events.ts。
**Interfaces:** EventEnvelope、ExecutorInput/ExecutionOutcome、EventSink与AgentExecutor按映射；RunBudget此时实现真实需要的check_cancelled/活跃deadline，P03再增加模型/工具原子计数。不提前给FakeAgent真实业务权限。

- [ ] 为共享契约所有事件类型写合法fixture；phase/plan等未来事件只定义schema和解析，不实现其业务。
- [ ] 测试seq<=0、缺run_id、未知status拒绝；JSON时间UTC；工具事件用同call_id配对。
- [ ] 扩展schema/type生成和--check，前端联合类型从同源导出。
- [ ] 跑`uv run pytest tests/unit/test_event_contracts.py -q`与生成检查。

### P02-T02：Run、Message、Event持久化

**Files:** Create `repositories/runs.py`、`repositories/messages.py`、`services/runs.py`；Modify indexes；Test `tests/integration/test_run_atomicity.py`。
**Interfaces:** RunService.create/append_event/events/get；Conversation有active_run_id；event唯一(run_id,seq)，请求唯一(owner_id,request_id)。

- [ ] 写并发创建测试：同thread不同request只一个成功，另一个ACTIVE_RUN_EXISTS；同request相同payload返回同run，不同payload409。
- [ ] create事务同时认领thread、建run、保存user message；append_event事务增seq并插事件；不允许先增seq再独立插event造成断档。
- [ ] terminal事务保存最终assistant、run_finished、run.status并释放active_run_id；message_id固定，崩溃重试不能重复append最终消息。
- [ ] 注入事务内异常确认无半条run/消息；执行`uv run pytest tests/integration/test_run_atomicity.py -q`。

### P02-T03：FakeAgent与SSE观察层

**Files:** Create `agent/fake_executor.py`、`services/chat.py`、`api/chat.py`、`tests/integration/test_chat_stream.py`。
**Interfaces:** ChatService.start返回run并交给进程级任务管理器；Executor.execute通过EventSink发事件；首事件run_started，流末stream_end。

- [ ] 写断开观察流后后台仍产出最终事件的测试；另测工具失败发error而非伪造成功。
- [ ] 后台task由服务lifespan保存强引用，记录失败回调；SSE轮询/订阅持久events，不能把图执行放在响应generator生命周期中。
- [ ] FakeAgent发固定示例文本/工具卡片且标simulation=true、无真实业务写入；断流后GET events仍可读实际进展。
- [ ] 完成/失败持久run_finished；waiting_input只在P04启用。网络无法发送末事件时DB仍保留状态，客户端依靠查询恢复。

### P02-T04：查询、取消、删除与重启

**Files:** Create `api/history.py`、`api/runs.py`；Extend services/runs；Test `tests/integration/test_run_lifecycle.py`、`test_owner_isolation.py`。
**Interfaces:** 共享history/run/events/cancel接口；cancel标cancel_requested，不以关闭HTTP连接实现。

- [ ] 写ownerA/B访问、删除、events重放测试；所有查询在DB带owner条件，错误404；运行中删除409。
- [ ] executor每次后续步骤前检查cancel；P02只读模拟无副作用，可确认停止后标cancelled，发run_finished/stream_end。已completed再cancel幂等返回状态。
- [ ] 启动时识别当前进程之外遗留created/running，标PROCESS_RESTARTED失败并释放thread锁；P04持久中断完成后才升级恢复策略。
- [ ] 执行两个测试文件，核对删除后无残留可访问的消息/event；审计信息保留策略在README说明。

### P02-T05：前端解析器和状态机

**Files:** Create `lib/sse-parser.ts`、`lib/event-reducer.ts`、`hooks/{useSSE,useChat,useHistory}.ts`、chat/sidebar组件；Test `frontend/src/tests/{sse-parser,event-reducer}.test.ts`。
**Interfaces:** SSEParser.push/finish、applyEvent；run状态、message_id和last_seq与UI组件分离。

- [ ] 把含中文的字节流在每个可能位置切片；解析结果应与整块解析完全相同。重复seq不追加第二次token；未知兼容事件可忽略，未知schema_version提示不兼容。
- [ ] 使用TextDecoder(stream=true)，按SSE空行断帧并处理CRLF；支持data多行和心跳注释；末尾不完整帧触发查询恢复。
- [ ] useSSE负责AbortController/释放观察连接；停止按钮调用cancel。刷新后每2秒查run/events，直到终态或waiting_input停止轮询并展示可用操作。
- [ ] 历史最终message与token重放按message_id合并，不重复拼接；跑Vitest、typecheck和build。

### P02-T06：浏览器验收与交付

**Files:** Create `tests/e2e/chat-flow.spec.ts`、`evidence/P02.md`；Update阶段验证与README。
**Interfaces:** 使用FakeAgent稳定输出作为fixture，测试不依赖LLM响应时间。

- [ ] E2E执行发送→工具卡片→刷新→历史，验证同message只出现一次；另测停止、切换会话、断开/恢复观察。
- [ ] 核对P02-A01..A06，测试重启后明确失败而非永久转圈；人工页面明显标假执行器。
- [ ] 跑P02 offline/browser；证据model_mode=fake，不能标真实模型已联调。
- [ ] 模块README、evidence、STATUS、spec更新后提交/推送/核对`phase-p02`，停止。
