# P02-fix1 并发缺口补修证据

status: implemented / offline_verified / browser_verified / ci_verified
stage: P02-fix1
delivery_state: pushed_main（7267378；CI run 40061149309，branch badge passing）；phase-p02-fix1 指向最终记录提交
base: phase-p02 d8415ce；review HEAD 34df3fa
environment: Windows 10.0.19045；venv Python 3.13.14（uv 0.11.27）；Node 24.11.0；npm 11.6.1；Next.js 16.4.2；MongoDB mongo:8.0 replica set `ta-rs`（127.0.0.1:27027）
model_mode: fake
executor: FakeAgent；不调用真实模型/MCP/订单写

## 修复范围

### F01 / R01 删除与创建事务互斥

- `delete_conversation` 不再事务外预查；每次事务内重新读 thread，检查 active_run_id 后通过 `threads.claim_for_delete` 条件写设置 `deleting=true`（要求 `active_run_id=None` 且未在删除）。
- `claim_thread` 同样要求 `deleting != true`；创建与删除在同一 thread 文档上竞争，只有一方取得资格。删除资格取得后在同一事务删除 messages/events/runs/thread。
- 创建遇到 deleting 返回 404；删除遇到活跃 run 返回 ACTIVE_RUN_EXISTS/409。transient retry 每次重读 thread。

### F02 / R02 聊天异步代次

- `useChat` 增加递增 `viewGenerationRef` 与失效入口：选择会话、新建、主动刷新、卸载都递增并 abort 旧观察。
- `loadThread`、`recoverRun`、`refreshAfterRun`、SSE onEvent/onEnd/onAbort/onError/onRecover 写入前核对代次/发送 token；旧操作不能改 state、URL、error、notice、sending。
- `selectThread` 即使点击当前已显示的 B 也会使 pending 的 A 失效（浏览器用例发现并修复）。
- `useSSE` 每次 start 有独立 AbortController；旧连接 end/abort/error 在控制器已被替换后直接丢弃回调。

### F03 / R03 预检查前发送互斥

- `send` 在第一次 `await ensureLocalSession()` 前同步设置 `sendingRef=true/sendToken`；第二次调用直接返回。
- 会话检查成功后才启动 SSE；检查失败释放 token 并可重试。检查返回时若视图代次已变，旧检查不得创建 run。
- 发送 token 区分锁归属；旧操作不能释放新发送。

### F04 / R04 预算注册窗口取消

- `ChatTaskManager` 新增 `register_budget`：create 返回后在任何 await 前注册 budget，再写 run_started；任务创建后 attach task。
- run_started 写完后在执行器启动前读取持久 `cancel_requested`，若已取消则 budget.cancel；窗口前/后取消都能在第一步前生效。
- 取消在公开接口仍写 DB flag；重复 cancel/completed cancel 幂等。

### F05 / R05 已有会话并发幂等

- `create_or_get` 每次事务开始时重新查 owner/request_id，校验 request_hash；相同 payload 直接返回原 run + False，不同 payload 409。
- 活跃冲突分支会读取 active_run_id 对应 run，request/hash 相同则返回原 run；外部对 ACTIVE 的短暂重查避免首事务未提交时误报 409。
- 事务返回值区分新建/已有，ChatService 只对 just_created 启动一次任务。

### F06 / R06 SSE 终态排空

- 抽出 `stream_run_events`：每轮持久 events；看到终态后继续按 after_seq 排空到 run.last_seq，只有持久 stream_end 才正常结束；有界重试避免无末事件无限循环。
- get 看到终态而第一批 events 为空/缺 stream_end 时仍会补发。

### F07 回归与交付

- 新增/扩展测试：R01 删除竞争、R05 已有 thread 同请求竞争、R04 run_started 窗口取消、R06 终态排空、useChat 5+1 个代次/发送/旧流用例、2 个浏览器并发场景。
- 模块 README、spec/plan、STATUS、本 evidence 更新；P00/P01 回归不倒退。

## 修复前确定性失败

在旧提交 `d8415ce` 的临时 worktree 中运行同一批新测试：

```text
backend old worktree: 3 failed, 7 passed
- test_delete_claim_prevents_deleting_a_new_run: DID NOT RAISE AppError（旧删除删掉了新 run）
- test_same_request_on_existing_idle_thread_race_is_idempotent: 旧实现 ACTIVE_RUN_EXISTS
- test_cancel_between_create_and_run_started_prevents_followup_steps:
  events 含 token/tool_started（旧实现继续调度）
- test_sse_drain.py: ImportError: cannot import name 'stream_run_events'
  （旧 API 没有终态排空实现）

frontend old worktree: 4 failed, 1 passed (5 个旧版 hook 用例)
- slow A 后显示 A 而不是 B
- newChat 后 pending A 又恢复 A
- 旧 A reject 写入 error
- ensureLocalSession pending 期间 sending=false
- 旧 stream end 用例在旧实现恰好通过（新增旧 abort 用例后未在旧 worktree 重跑，不冒充）
```

修复后同一批新用例全部通过；新增的 R01 反向删除后创建 404、旧 abort 不释放新发送、活跃 thread 同 request 等断言也通过。

## 实际检查

| 检查 | 结果 |
|---|---|
| `uv run pytest tests/unit -q` | exit 0，**33 passed** |
| `uv run pytest tests/integration -q` | exit 0，**78 passed**（含 P00/P01/P02 回归） |
| 前端测试 | 6 files / **23 passed** |
| `verify_stage P02 --mode offline --report .runtime/reports/P02-fix1-offline.json` | exit 0，**9/9**，163.84s |
| `verify_stage P02 --mode browser --report .runtime/reports/P02-fix1-browser.json`（先启动 3030/8030） | exit 0，**1/1**，27.83s；E2E **6 passed** |
| `export_contracts --check` | exit 0 |
| 前端 typecheck/build | exit 0 |
| GitHub Actions | push `7267378` 后 run [40061149309](https://github.com/newerwell/technologyagent/actions/runs/40061149309)，仓库 CI badge `passing` | 实现阶段通过；docs-only final run 以最终核对为准 |

P02-fix1 offline 明细：

```text
db_init            exit 0  passed     773.25 ms
compatibility      exit 0  passed   15165.60 ms
seed               exit 0  passed    2412.78 ms
unit_tests         exit 0  passed    3965.68 ms  (33 passed)
integration_tests  exit 0  passed  125453.62 ms  (78 passed)
frontend_typecheck exit 0  passed    3251.08 ms
frontend_tests     exit 0  passed    5641.63 ms  (23 passed)
frontend_build     exit 0  passed    6762.56 ms
contract_check     exit 0  passed     414.22 ms
```

关键覆盖：

- R01：idle thread→删除读后暂停→新 run 提交→删除返回 409，run/user/event/thread 保留；删除成功后再创建返回 404。
- R04：run_started 写入挂起→cancel 成功→放行；事件仅 run_started/run_finished/stream_end，无 token/tool，status cancelled。
- R05：旧 run 完成后的 idle thread，两同 request 首查都空后竞争，返回同 run、一个 just_created、唯一 user message。
- R06：首批 events 空/缺 stream_end，get 已终态时仍排空出唯一 run_finished/stream_end。
- R02/R03：实际 hook deferred 用例覆盖 A/B、newChat、旧 error、ensure pending 连续 send、旧 abort 不释放新发送；浏览器覆盖延迟 A→B、预检查锁。

## 浏览器证据

- E2E 6/6（Chrome channel）：
  1. 发送/工具卡/刷新去重
  2. 运行中刷新恢复
  3. 停止 cancelled
  4. 切换会话
  5. 延迟 A conversation→选 B→放行 A：URL/消息保持 B
  6. 拦截 session 预检查→连续输入发送：按钮锁定、只 1 个 chat stream
- 原 [P02-chat.png](../evidence/P02-chat.png) 仍代表 FakeAgent UI；fix1 无视觉改版，新增并发场景以 E2E 文本证据为准。

## 未运行与限制

- 未调用真实模型/MCP/订单写/ERP/沙箱；FakeAgent 保持。
- 未 reset 开发库；测试仅使用 `technologyagent_test_*` 并清理。
- R02 旧 worktree 只跑了最早 5 个 hook 用例；新增旧 abort 用例只在修复后运行，未补跑旧版，不把它写成修复前失败。
- 启动恢复仍是 PROCESS_RESTARTED failed，不是 checkpoint 恢复。
- E2E 需要本机 Chrome 和已启动服务；CI offline 不运行 browser。

## 下一阶段

P02-fix1 待复核；通过后 P03 才接入真实模型/工具。
