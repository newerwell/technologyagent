# frontend 前端应用

## 职责

P01–P04 的 Next.js 页面包括工程状态页、`/data` 业务数据页、`/chat` 对话页与 `/orders` 订单审批页。P04 卡片只展示服务器草稿金额与版本，审批决定由持久化工作流恢复；订单结果从 owner-scoped API 查询/对账。仍不包含 ERP、专家或沙箱。

## 目录

```text
frontend/
├─ src/app/                 # layout、page、/chat、/data、/api/chat/stream 直通代理
├─ src/components/common/   # StatusPanel 及其测试
├─ src/components/data/     # 数据页、库存/供应商/报价表、补货预览
├─ src/components/chat/     # 消息、工具卡片、输入、聊天页
├─ src/components/sidebar/  # 会话列表
├─ src/hooks/               # useSSE、useChat、useHistory
├─ src/lib/api.ts           # 统一 fetch、Envelope、ApiError、超时
├─ src/lib/events.ts        # 由 scripts/export_contracts.py 生成
├─ src/lib/sse-parser.ts    # 跨 chunk SSE 解析
├─ src/lib/event-reducer.ts # run+seq 去重/工具卡片/历史合并
├─ src/lib/domain-types.ts  # 由 scripts/export_contracts.py 生成
├─ src/lib/format.ts        # 金额/时间展示
├─ vitest.config.ts         # Vitest + jsdom + Testing Library
├─ playwright.config.ts     # testDir 指向仓库 tests/e2e（P02 起使用）
└─ scripts/run-next.mjs     # 从 FRONTEND_PORT 启动 dev/start，固定绑定 127.0.0.1
```

## 公开接口（浏览器侧）

- `GET /health`、`GET /ready`、`POST /api/session/local`、`GET /api/session/me` 均通过 Next 同源 rewrite 转发到 `http://127.0.0.1:API_PORT`。
- P01 数据页使用 `GET /api/parts|suppliers|quotes|inventory|inventory/warnings|inventory/summary` 与 `POST /api/replenishment/preview`；金额展示用 `formatMoney`，补货计算只在后端。
- P02/P03 聊天页使用 `POST /api/chat/stream`、`GET /api/conversations`、`GET /api/runs/{id}/events`、`POST /api/runs/{id}/cancel`。`/api/chat/stream` 由 Next route handler 直接转发 ReadableStream，避免 rewrite 缓冲 SSE。
- P03 工具卡显示 name、args_summary、result_summary、source 和 call_id；页面从 run_started 的 model_mode 显示 ScriptedModel 或 Live Model。

## P04 订单审批

- `/orders` 展示草稿/待审批和真实订单列表；金额来自服务端 cents，不由前端计算审批金额。
- `/chat` 根据 pending interrupt 提交 supplement/edit/approve/reject；刷新后从同 run 重新加载中断和草稿版本。
- `components/approval/README.md` 说明 ApprovalCard/SupplementForm 的接口与边界。
- 核验：`npm --prefix frontend run typecheck`、`npm --prefix frontend run test -- --run`、`npm --prefix frontend run build`、`npm --prefix frontend run test:e2e`。
- `lib/api.ts` 统一处理 `{ok,data,error,meta}`，失败抛出 `ApiError`，请求带 `credentials: "include"`，不拼接用户 ID。
- 请求超时 8 秒，页面不会无限 loading；失败时显示可读错误和“重新检测”。

## P09 通用提案

- `/orders`对改单显示后端保存的旧/新物料行、具体单位、单价、行额和总额；不从模型正文推算审批金额。
- `/chat`在`mutation_prepare`后显示同一run的持久待确认中断，批准/拒绝经`/api/runs/{run_id}/resume`提交。刷新/恢复后仍按原owner、run、审批版本及服务端payload处理。
- Playwright覆盖订单页改单金额与通用提案批准/拒绝；原run图调用与Mongo中断恢复由`tests/integration/test_business_workflow.py`覆盖。

## 运行

```powershell
npm --prefix frontend ci
npm --prefix frontend run build
.\start.ps1
```

开发模式（端口取 `FRONTEND_PORT`，默认 3030；只监听 127.0.0.1）：

```powershell
npm --prefix frontend run dev
```

生产模式（先按当前 API_PORT 构建；同样只监听 127.0.0.1）：

```powershell
npm --prefix frontend run build
npm --prefix frontend run start
```

`start.ps1` 每次实际启动新前端进程前都会用当前 `API_PORT` 执行 `next build`，不再因为 `.next/BUILD_ID` 存在就复用旧构建；构建目标记录在 `.runtime/frontend-build.json`。修改 `API_PORT` 或 `FRONTEND_PORT` 时必须先 `stop.ps1` 再启动；已在运行的同一配置重复启动仍保持幂等。启动成功条件包含经前端的同源 `/health` 与 `/ready`，不会只因首页 200 报成功。

## 检查

```powershell
npm --prefix frontend run typecheck
npm --prefix frontend run test -- --run
npm --prefix frontend run build
```

P02–P04 的 Playwright 使用本机 Chrome channel，测试位于仓库根 `tests/e2e`；运行 `npm --prefix frontend run test:e2e` 需要先启动 3030/8030/9030。`verify_stage P04 --mode browser` 执行 FakeAgent 全量验收；真实模型验收只运行 P04 `order-flow.spec.ts` 场景，并设置 `MODEL_MODE=live`、`P04_EXPECT_LIVE=1`、`P04_RESTART_BACKEND=1`。

## 错误与限制

- `/ready` 503 时页面读取错误 Envelope 中的 `data.checks` 展示降级原因。
- 页面首次访问先尝试 `/api/session/me`，未登录的 401 是预期流程，随后调用 `/api/session/local`。
- 不使用 `NEXT_PUBLIC_*` 传递身份或密钥；后端端口由 `API_PORT` 在 Next 配置中读取。
- 本地会话 Cookie 为 HttpOnly、SameSite=Strict；浏览器只通过 127.0.0.1 的同源 rewrite 访问 API。
- P03 的 `/chat` 从 run_started 显示 model_mode=fake/live；fake 明确为 ScriptedModel，不创建订单/产物。
- P03 仍不提供订单写、审批、专家或 artifact；`actionable=false` 只是预览不可下单。
- 数据页筛选变化会重置库存页码；请求失败会清空上一轮数据与金额。
