# P02 补修 Implementation Plan

> **For agentic workers:** 其他实施 Agent 只执行本补修，按 executing-plans 逐项实施；独立前后端任务可使用 subagent-driven-development。当前规划聊天不改产品代码，不开始 P03，不移动既有标签。

**Goal:** 修复会话删除、请求幂等、取消、末事件与聊天异步状态的 6 项并发缺口。
**Architecture:** 保持现有 services/repositories/ports、事件 v1 和 API；后端通过事务条件写保证竞争结果，前端通过操作代次与同步发送互斥隔离旧请求。不引入任务队列或新执行框架。
**Tech Stack:** 现有锁定的 Python/FastAPI/PyMongo、Next.js/React、Vitest/Playwright；不升级依赖。
**Spec:** [P02 复核](../reviews/2026-10-24-P02-review.md)、[P02 spec](../specs/P02-chat-streaming.md)、[共享契约](../specs/CONTRACTS.md)。

状态：F01–F06 已实现并本地验证；F07 远程交付/标签核对待完成。输入基线 d8415ce；P00 两项、P01 四类补修已复核关闭。

## Global Constraints

- FakeAgent 明确标注，不能调用真实模型、MCP 产品或写采购业务数据。
- owner 条件、事件持久化后再发送、seq 单调、同 thread 单活跃、request_id 幂等、断线不取消保持。
- 不 reset 开发库；测试库必须 technologyagent_test_*；保留 .dsh-meow 和无关改动。
- 原 phase-p00/phase-p00-fix1/phase-p01/phase-p01-fix1/phase-p02 不动，新标签 phase-p02-fix1。

## Review Focus

检查后认领与事务重试→F01；旧加载/恢复/流回调污染当前视图→F02；首个 await 前连续发送与切换→F03；取消早于预算注册→F04；已有 thread 的同幂等请求→F05；空事件查询后刚提交终态→F06。全量证据与上传→F07。

## 文件分工

| 文件 | 本次职责 |
|---|---|
| backend/app/services/runs.py、repositories/runs.py | 删除资格、事务内幂等竞争；保留公共服务签名 |
| backend/app/services/chat.py、必要 agent/budget.py | 预算注册和持久取消状态交接 |
| backend/app/api/chat.py | 终态流排空 |
| frontend/src/hooks/useChat.ts、useSSE.ts | 当前视图代次、回调归属、发送互斥与卸载清理 |
| tests/integration/test_run_atomicity.py、test_run_lifecycle.py、test_chat_stream.py | Mongo 事务/服务/观察流并发回归 |
| frontend/src/hooks/useChat.test.tsx（新增）、必要 useSSE.test.tsx | deferred promise 驱动实际 hook 的状态测试 |
| tests/e2e/chat-flow.spec.ts | 限速切换、新对话、重复发送浏览器证据 |
| 各模块 README、evidence/P02-fix1.md（新增）、STATUS、spec/plan | 如实记录接口语义、覆盖与交付 |

### P02-F01：删除和创建互斥（R01）

**Interfaces:** `delete_conversation(thread_id, ctx) -> DeleteResult` 不变；运行中返回 ACTIVE_RUN_EXISTS/409，无权限仍 404。仓储增加明确的 owner/thread/idle 条件删除或等价认领接口，由服务事务调用。

- [x] 在真实 Mongo 测试库先写失败测试：idle thread→DELETE 读后暂停→创建新 run 提交→继续删除。断言删除应 409，run/user/event/thread 完整保留。
- [x] 增加反向顺序：删除先取得资格，随后创建只能得到 404/合法竞争结果，不能创建悬空 run。覆盖事务发生 transient conflict 重试后重新判定。
- [x] 每次事务内重新检查当前 thread，以条件写参与 thread 认领竞争；删除关联记录与删除 thread 在同一事务，争用时不清理活跃运行。禁止仅事务外预查。
- [x] 运行 lifecycle/atomicity 目标测试，再验证普通空闲删除及跨 owner 404。提交本项源码与测试。

### P02-F02：隔离当前会话状态（R02）

**Interfaces:** `useChat` 对外 API 保持；内部建立递增视图代次，异步操作捕获代次、目标 thread/run；失效回调不写 state、URL、error、notice 或 sending。`useSSE` 每次连接必须区分自己的控制器/代次。

- [x] 用实际 hook+deferred API 写失败测试：A pending→B完成→A成功；A pending→newChat→A成功；旧 A reject/finally 不影响 B；断流恢复和终态 refresh pending 时切换，新状态不变。
- [x] 定义统一失效入口：选择、新建、主动刷新、卸载；loadThread、recoverRun、refreshAfterRun 及全部 SSE 回调在写入前校验。AbortController 作为取消观察手段，不能替代写回守卫。
- [x] 旧流 abort/end/error 晚到不得释放新流 sending 或污染新 run；避免把 A 的消息 merge 到 B。补旧事件在新视图为空时到达、新流开始后旧 abort、卸载后的测试。
- [x] 真实浏览器受控延迟 A 再切 B/新对话，核对消息、当前选中、URL 与下一次请求 thread_id；只关观察流，后台任务仍可在历史查询。运行 hook/parser/reducer 测试后提交。

### P02-F03：预检查前认领发送（R03）

**Interfaces:** `send(text) -> Promise<void>` 不变；同步占用发送状态，失败或当前操作完成时释放；失效旧操作不能释放新操作锁。

- [x] 失败测试：ensureLocalSession pending，连续 send 两次，仅启动一个流，等待期间 busy/sending 为 true。断言有效发送正文和唯一 request_id，不仅检查按钮 disabled。
- [x] 第一次 await 前同步认领；认证失败可重试；捕获 F02 代次，预检查完成后失效则不得创建运行。必要时用发送操作 token 区分锁归属。
- [x] 覆盖预检查中 newChat/切换→旧预检查成功或失败，不启动旧 run、不覆盖当前 error/sending；新视图仍可正常发送。保留首条消息建立新 thread 和已有 thread 续发。
- [x] 浏览器拦截会话检查响应，发送后重新输入并连续提交，检查网络 POST 与新增运行均为一次；不要把输入框清空导致的暂时禁用误当发送锁。与 F02 一并跑目标测试后提交。

### P02-F04：关闭预算注册前取消窗口（R04）

**Interfaces:** `ChatService.start/cancel`、RunBudget 检查契约不变；DB flag 为可信事实；本进程预算及时停止后续调度。

- [x] 服务调度失败测试：create 已提交，run_started 写入挂起；另请求 cancel 得成功；放行 start，断言执行器下一步骤前已观察取消，不产生后续 token/工具调度，最终仅一次 cancelled 终态。
- [x] 注册通知接收者后、执行器启动前同步持久 cancel_requested，或用等价无丢失交接。检查读取 flag 期间再 cancel 也能通知已注册预算；不要仅在 start 最初检查一次。
- [x] 覆盖正常运行中取消、重复取消、completed 后取消、启动异常清理预算；在真实 Mongo 集成测试中安排该窗口。FakeAgent 不增加业务副作用。
- [x] 跑 chat_stream/atomicity/lifecycle 目标测试，记录取消时间点和之后事件，提交。

### P02-F05：已有会话并发幂等（R05）

**Interfaces:** `create_or_get(thread_id,message,request_id,ctx) -> (RunView,bool)` 不变；相同 owner/request/payload 返回同 run，just_created 只一次；不同 payload 为 IDEMPOTENCY_CONFLICT；不同请求争用活跃 thread 为 ACTIVE_RUN_EXISTS。

- [x] 真 Mongo 失败测试：先建立并完成旧 run，两个相同新请求首次查重都为空，再继续竞争；两个均返回同 run、唯一用户消息、唯一 run_started/执行器启动。
- [x] 把重查请求与 hash 校验纳入每次事务/冲突重试；保证 active 检查不会优先吞掉合法重放。事务返回值也须能区分已有与新建，防止 ChatService 重启同一任务。
- [x] 同时覆盖新 thread 重放、已有 thread 变更 message、不同 owner 同 request_id、不相同 request_id 争同 thread。保持唯一索引，不能用进程全局锁掩盖数据库契约。
- [x] 跑 atomicity 与 chat 目标测试，核对数据库实体数量，提交。

### P02-F06：SSE 正常发送终态末事件（R06）

**Interfaces:** POST 流和 EventEnvelope v1 不变；持久事件是唯一内容源，正常结束必须发到对应 stream_end，不能合成重复末事件。

- [x] 先写确定性失败测试：一次 events 查询返回空，紧接 finish 提交，再 get 返回终态；断言响应仍包含唯一 run_finished/stream_end，seq 无遗漏。
- [x] 观察终态后继续排空到其 last_seq，收到持久 stream_end 才结束。明确真实异常时的退出/报错路径，不能在没有末事件时无限循环。
- [x] 覆盖已结束 run 的 request_id 重放、正常长流、finish 落在两次读取之间、连接断开不取消。测试可用可控依赖精确调度，并补真实服务+数据库流结果一致性。
- [x] 跑 chat_stream 与前端 parser/reducer，提交。

### P02-F07：回归、文档与 Git 交付

**Interfaces:** 历史 P02 证据保留；新增补修证据，与“基础测试通过、并发问题待修”的历史状态区分。

- [x] 运行 `uv run python -m scripts.verify_stage P02 --mode offline --report .runtime/reports/P02-fix1-offline.json`，确认最终退出码与每项结果；包含 P00/P01 回归，不固定测试数量。
- [x] 在单独测试库/本机服务运行 `uv run python -m scripts.verify_stage P02 --mode browser --report .runtime/reports/P02-fix1-browser.json`；新浏览器场景有实际执行证据。运行 contracts --check，检查 diff。
- [x] 新建 evidence/P02-fix1.md，写修复前失败、修复后断言、真实 DB 与内存/浏览器的证据区别；更新模块 README、STATUS、spec/plan 和实施入口。真实模型/MCP/订单仍 not_run。
- [x] 清理本次临时库、进程、生成的临时规则/文件；保留原有 .dsh-meow，不改 .env。不以测试通过取代 R01–R06 覆盖说明。
- [ ] 显式暂存本补修路径、commit、push origin/main，核对远程 SHA；等待并核对本次实现 CI。最终记录提交后推新 annotated phase-p02-fix1 并核对解引用 SHA。原标签全部保持，失败如实报告。
- [ ] 完成交付后停止，交回规划者复核；不得自动开始 P03。

## 复制给实施 Agent

```text
只完成 TechnologyAgent 的 P02-fix1，不开始 P03。仓库 technologyagent（先确认实际绝对路径和 origin）。读取 AGENTS.md、docs/reviews/2026-10-24-P02-review.md、docs/implementation/P02-followup.md、P02 spec/原 plan、共享契约和 STATUS。
按 F01–F07 修复 R01–R06：删除与创建事务互斥、聊天异步代次、会话预检查前发送互斥、预算注册窗口取消、已有会话并发幂等、SSE 终态排空。每项先保留确定性失败用例，再修复并运行相称测试，不能只增加普通顺序测试。
保持 fake，不接真实模型/MCP 产品/订单写，不 reset 开发库，保留无关文件；P00/P01 已关闭问题不得倒退。完成 P02 offline、browser、模块说明和 evidence/P02-fix1.md，显式提交并推送 origin/main，核对 CI 与远程 SHA；用新 annotated phase-p02-fix1，不能移动旧 phase-p02 等标签。交付后停止，报告待复核。
```