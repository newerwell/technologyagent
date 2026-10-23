# P00-F01/F02 补修证据

status: implemented / offline_verified / browser_verified / real_proxy_verified / ci_verified
stage: P00 fix1
delivery_state: pushed_main（59d98e3；CI run 39959955218 success）；phase-p00-fix1 待创建/核对
environment: Windows 10.0.19045；venv Python 3.13.14；Node 24.11.0；npm 11.6.1；Next.js 16.4.2；Docker 29.9.2；MongoDB mongo:8.0 replica set `ta-rs`（127.0.0.1:27027）
model_mode: fake（无 MODEL_API_KEY；P00 不调用模型）
data_source: none（P00 无业务数据；测试使用 `technologyagent_test_*` 库并删除）

## 修复范围

### P00-F01 本机监听与来源边界

- `frontend/scripts/run-next.mjs`：dev/start 都显式传 `-H 127.0.0.1`。
- `start.ps1`：Uvicorn 显式 `--host 127.0.0.1 --no-proxy-headers`；Next 生产入口 `start -H 127.0.0.1`。
- `backend/app/api/dependencies.py`：新增本机边界校验：
  - 只接受回环 socket peer；
  - Host 只接受 `127.0.0.1/localhost/[::1]` + `API_PORT` 或 `FRONTEND_PORT`（兼容 Next rewrite 保留前端 Host 或改写为后端 Host）；
  - 带 Origin 时只接受前端同源 `http://127.0.0.1|localhost|[::1]:FRONTEND_PORT`；无 Origin 的本机脚本允许；
  - `X-Forwarded-For` 不参与身份判定。
- 本地会话 Cookie 统一为 `HttpOnly; SameSite=Strict; Path=/`。
- 新增真实链路测试 `tests/integration/test_local_startup_boundary.py`，启动真实 Uvicorn + Next dev，不使用 TestClient 冒充代理链。

### P00-F02 当前配置、源码与生产构建一致

- `start.ps1` 每次实际新启动前端前都执行 `npm --prefix frontend run build`，不再按 `.next/BUILD_ID` 复用旧构建。
- 构建目标写入 `.runtime/frontend-build.json`（`api_port`/`frontend_port`）；前端进程在运行时若配置变化，重复 `start.ps1` 明确拒绝并要求先 `stop.ps1`。
- 启动成功条件增加经前端的同源 `/health` 与 `/ready`，校验响应来自 API 且 db/transaction ready；失败会回收本次新增进程并报错，不会只因首页 200 报成功。
- 若检测到旧版本登记的进程缺少 `--no-proxy-headers` 或 `-H 127.0.0.1`，启动脚本拒绝复用并要求先 `stop.ps1`，避免升级后继续使用旧监听参数。
- 新增 `tests/integration/test_startup_configuration.py`：静态检查启动参数，并用隔离的 A/B 端口真实构建，断言 `routes-manifest.json` 的三条 rewrite 跟随当前 `API_PORT`。

## 实际执行

| 检查 | 命令/步骤 | 实际结果 |
|---|---|---|
| 真实 Next→Uvicorn 链路 | `uv run pytest tests/integration/test_local_startup_boundary.py -q -s` | exit 0；1 passed；Next 日志 `Local: http://127.0.0.1:60240`；正常同源会话创建/读取成功；恶意 Origin + 伪造 XFF 返回 403；直接伪造 Host 返回 403 |
| 回环监听 | 上述测试连接本机非回环 IPv4 `172.31.176.1` 的 API/前端端口 | 均连接失败；实际监听地址为 127.0.0.1 |
| 构建配置 A/B | `uv run pytest tests/integration/test_startup_configuration.py -q` | exit 0；3 passed；两次构建的 `/health`、`/ready`、`/api/:path*` 目标分别跟随 A/B `API_PORT` |
| 全量集成测试 | `uv run pytest tests/integration -q` | exit 0；**31 passed**（含真实代理链与 A/B 构建） |
| start.ps1 A/B | 隔离测试库 + API 8130/前端 3130 启动，停止后 API 8131 重启 | A/B 均 exit 0；A 的 listeners 为 127.0.0.1:8130/3130；同源 /health=/true(api)、/ready=ready(db=ok,tx=ok)；A 直连 8130 true；LAN 3130/8130 均 false；marker=8130/3130；进程数 2 |
| start.ps1 幂等 | 同配置再次 `start.ps1` | exit 0；输出“已在运行，未启动重复实例”；进程数仍 2；同源 /health、/ready 通过 |
| 配置变更保护 | 运行中把 API_PORT 改为 8131 后再次 `start.ps1` | 拒绝并提示旧端口进程（backend:8130），要求先 `stop.ps1`；进程数仍 2，无重复实例 |
| 停止与重建 | `stop.ps1` 后以 API 8131 重启 | stop exit 0；marker 删除；8130/3130 关闭；B 启动 exit 0；同源 /health、/ready 通过；直连 8131 true、8130 false；routes-manifest 的 health/ready 均为 `http://127.0.0.1:8131/...`；marker=8131 |
| 清理 | stop + 删除测试库 | 8130/8131/3130 均关闭；测试库删除；无残留进程 |
| npm run start 入口 | `FRONTEND_PORT=3031 npm --prefix frontend run start` | 页面 HTTP 200；监听地址为 127.0.0.1:3031；测试后进程回收、端口关闭 |
| Chrome 回归 | 默认 8030/3030 + 测试库，Chrome headless 打开页面 | HTTP 200；标题“TechnologyAgent · P00 工程底座”；本地会话建立 owner=local-owner；Cookie HttpOnly + **SameSite=Strict** + Path=/；仅首次未登录 401 控制台记录 |
| 浏览器截图 | `.runtime/P00-fix1-page.png` | 已复制到 `evidence/P00-fix1-page.png` |
| 兼容探针 | `uv run python -m scripts.check_compatibility` | 8/8 通过；checkpointer 文案改为“同一 graph/saver 实例保存/读取/继续”，进程重启恢复留 P04 |
| 阶段验证 | `uv run python -m scripts.verify_stage P00 --mode offline --report .runtime/reports/P00-fix1-offline.json` | exit 0；6/6 checks passed；总耗时 114.13s；`integration_tests` 输出 31 passed |
| GitHub Actions | push 59d98e3 后远程 run [39959955218](https://github.com/newerwell/technologyagent/actions/runs/39959955218) | success；checkout/setup/install/init/verify/upload 全部步骤 success |

start.ps1 A/B 关键事实：

```text
A listeners: 127.0.0.1:8130, 127.0.0.1:3130
A frontend /health: ok=True component=api
A frontend /ready : ok=True status=ready db=ok tx=ok
A marker: api=8130 frontend=3130
A duplicate start: 未启动重复实例；process_count=2
A change API_PORT without stop: rejected (backend:8130)
A stop: 8130/3130 closed; marker removed
B start with API=8131: success; /health + /ready via frontend true
B routes: health=http://127.0.0.1:8131/health; ready=http://127.0.0.1:8131/ready
B direct 8130=false; 8131=true; marker=8131
```

verify_stage 报告真实退出码（`.runtime/reports/P00-fix1-offline.json`）：

```text
db_init            exit 0  passed   1237.98 ms
compatibility      exit 0  passed  16985.76 ms
integration_tests  exit 0  passed  76598.58 ms  (31 passed in 71.58s)
frontend_typecheck exit 0  passed   4200.57 ms
frontend_tests     exit 0  passed   5569.08 ms
frontend_build     exit 0  passed   9538.56 ms
```

## 仍未执行/限制

- GitHub Actions 已对 59d98e3 实际执行并通过（run 39959955218）；旧 run 不算 fix1 的 CI。
- Playwright E2E 仍无 P00 用例；P02 起执行。
- 真实模型、MCP 产品服务、沙箱、ERP 与采购业务仍属后续阶段。
- 本地会话仍只用于单机开发；生产身份认证是 P09 前条件。
- `stop.ps1` 按设计不关闭 MongoDB 容器。
- 本次浏览器回归使用测试库并在停止后删除，不向开发库写入测试会话。

## 下一阶段输入

- 等待复核 P00-F01/F02 与 `phase-p00-fix1`；复核通过后再进入 [P01 计划](../docs/implementation/P01-implementation.md)。
- 保留原 `phase-p00` 指向 419ab236abbb0daf090230928c3bc81b7372c068，不移动/重写。
