# frontend 前端应用

## 职责

P00 的 Next.js 页面只展示项目名、API 存活、依赖就绪、能力状态和本地会话身份。它明确标注当前阶段不包含采购查询、聊天、真实模型、订单或沙箱。P02 起才接入聊天与事件流。

## 目录

```text
frontend/
├─ src/app/                 # layout、page、globals.css、icon
├─ src/components/common/   # StatusPanel 及其测试
├─ src/lib/api.ts           # 统一 fetch、Envelope、ApiError、超时
├─ vitest.config.ts         # Vitest + jsdom + Testing Library
├─ playwright.config.ts     # testDir 指向仓库 tests/e2e（P02 起使用）
└─ scripts/run-next.mjs     # 从 FRONTEND_PORT 启动 dev/start，固定绑定 127.0.0.1
```

## 公开接口（浏览器侧）

- `GET /health`、`GET /ready`、`POST /api/session/local`、`GET /api/session/me` 均通过 Next 同源 rewrite 转发到 `http://127.0.0.1:API_PORT`。
- `lib/api.ts` 统一处理 `{ok,data,error,meta}`，失败抛出 `ApiError`，请求带 `credentials: "include"`，不拼接用户 ID。
- 请求超时 8 秒，页面不会无限 loading；失败时显示可读错误和“重新检测”。

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

P00 的 Playwright 只配置命令与 `tests/e2e` 目录，实际浏览器用例从 P02 开始；`test:e2e` 在 P00 未运行，不作为通过依据。

## 错误与限制

- `/ready` 503 时页面读取错误 Envelope 中的 `data.checks` 展示降级原因。
- 页面首次访问先尝试 `/api/session/me`，未登录的 401 是预期流程，随后调用 `/api/session/local`。
- 不使用 `NEXT_PUBLIC_*` 传递身份或密钥；后端端口由 `API_PORT` 在 Next 配置中读取。
- 本地会话 Cookie 为 HttpOnly、SameSite=Strict；浏览器只通过 127.0.0.1 的同源 rewrite 访问 API。
- P00 没有业务页面、聊天、事件 reducer 或 artifact 预览。
