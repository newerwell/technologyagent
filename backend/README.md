# backend 后端应用

## 职责

P01–P08 的 FastAPI 应用提供本地目录、对话/审批、采购订单与库存收发闭环、Provider和ERP HTTP适配器。P08新增Receipt/Movement事务、通用提案以及23项MCP业务工具；真实ERP字段/账号尚未联调时不声明live通过。fake模式明确为ScriptedModel；live模型需真实模型配置与显式验收启用。

## 目录

```text
backend/app/
├─ main.py                 # 应用组装、中间件、异常转换、生命周期
├─ config.py               # Settings / load_settings / 密钥脱敏
├─ bootstrap.py            # Container 与依赖组装
├─ contracts/
│  ├─ common.py            # Envelope、Page、AppError、RequestContext、Clock
│  ├─ domain.py            # P01 实体、查询请求与预览模型
│  ├─ events.py            # P02 事件、run/thread/message DTO、ChatRequest
│  ├─ agent.py             # 执行器/模型消息与 delta 契约
│  ├─ domain-schema.v1.json
│  └─ events-schema.v1.json
├─ api/
│  ├─ health.py            # GET /health、GET /ready
│  ├─ session.py           # POST /api/session/local、GET /api/session/me
│  ├─ catalog.py           # /api/parts、/api/suppliers、/api/quotes
│  ├─ inventory.py         # /api/inventory、warnings、summary、preview
│  ├─ chat.py              # POST /api/chat/stream（SSE）
│  ├─ history.py           # /api/conversations
│  ├─ runs.py              # run 查询/events/cancel
│  └─ dependencies.py      # 容器注入、请求 ID、Cookie 身份解析
├─ domain/                 # 纯函数金额、库存状态与补货规则
├─ ports/                  # CatalogReader/InventoryReader/AgentExecutor/ModelPort/ToolRegistry
├─ agent/                  # GraphExecutor、预算、ScriptedModel、evidence
├─ repositories/
│  ├─ mongo.py             # AsyncMongoClient、真实事务上下文
│  ├─ indexes.py           # collection 约定、schema_version=1、幂等索引
│  ├─ sessions.py          # 会话摘要持久化
│  ├─ catalog.py           # 零件/供应商/报价读取
│  ├─ inventory.py         # 库存筛选/分页/范围读取
│  ├─ runs.py              # thread/run/event 读取、事务辅助与使用计数
│  ├─ messages.py          # user/最终 assistant message
│  └─ mcp_tokens.py        # P03 短期 MCP token 摘要
├─ services/
│  ├─ sessions.py          # 随机 token + HMAC 摘要 + 24h 过期
│  ├─ readiness.py         # ping/primary/事务回滚探针
│  ├─ seeding.py           # fixtures 校验、manifest 与只补缺失 seed
│  ├─ baseline_repair.py   # P01-fix1 旧基线显式修正
│  ├─ catalog.py           # 目录/库存查询与展示派生值
│  ├─ replenishment.py     # 补货预览用例
│  ├─ runs.py              # run/event/message 事务、取消、孤儿恢复、预算计数
│  ├─ chat.py              # 执行器后台任务与 SSE 观察
│  └─ mcp_tokens.py        # 每 run MCP token 签发/解析
└─ README.md
```

P08 `InventoryMutationService`与`BusinessMutationService`实现本地事务；`integrations/{local_provider,erp_provider}.py`声明来源与能力。订单页`/api/mutations/proposals`用于用户查看/决定通用提案。ERP配置名与真实接口限制见`docs/erp-mapping.md`。

仓库根的 `mcp_server/` 是 P03 独立 Streamable HTTP 进程，注册 9 个只读工具；`backend/app/integrations/` 是模型/MCP 适配。

## 公开接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /health | 只表示进程存活，不检查依赖，不泄露配置 |
| GET | /ready | db/primary/事务/model/mcp/sandbox 状态；数据库不可用返回 503 |
| POST | /api/session/local | 仅 APP_MODE=local、回环 socket peer、允许的 Host/Origin；请求体 owner_id 被忽略 |
| GET | /api/session/me | 需要 Cookie；返回服务端解析的 owner_id |
| GET | /api/parts、/api/suppliers、/api/quotes | P01 合成目录查询；分页 1..100；支持名称/ID 筛选 |
| GET | /api/inventory、/api/inventory/warnings、/api/inventory/summary | 库存分页、预警与全量汇总 |
| POST | /api/replenishment/preview | 缺口、候选报价、推荐、缺失字段与 snapshot/source 依据 |
| POST | /api/chat/stream | P02 SSE；thread_id?、message、request_id；首事件 run_started，末事件 stream_end |
| GET | /api/conversations、/api/conversations/{thread_id} | 当前 owner 会话列表/详情 |
| DELETE | /api/conversations/{thread_id} | 删除；运行中 409 |
| GET | /api/runs/{run_id}、/api/runs/{run_id}/events?after_seq=N | 状态与持久事件重放 |
| POST | /api/runs/{run_id}/cancel | 请求停止，不通过断开连接取消 |

普通响应统一为：

```json
{"ok": true, "data": {}, "error": null, "meta": {"request_id": "...", "data_source": "none", "as_of": "...", "scope": "anonymous"}}
```

失败时 `ok=false`，`error={code,message,retryable}`。P00 新增错误码：`UNAUTHENTICATED/401`、`LOCAL_SESSION_DISABLED/403`、`DEPENDENCY_UNAVAILABLE/503`。

## 配置

从环境变量或项目根目录 `.env` 读取；`.env.example` 是模板。主要字段：`APP_MODE`、`FRONTEND_PORT`、`API_PORT`、`MCP_PORT`、`MONGODB_URI`、`MONGODB_DATABASE`、`MODEL_*`、`LOCAL_SESSION_SECRET`、`STORAGE_ROOT`。密钥使用 `SecretStr`，配置摘要与日志不输出明文。

## 运行例子

```powershell
uv sync --frozen --group dev
docker compose up -d mongodb
uv run python -m scripts.init_db
uv run python -m scripts.seed
.\start.ps1
```

单独启动 API（必须关闭代理头信任）：

```powershell
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8030 --no-proxy-headers
```

## 测试

```powershell
uv run pytest tests/integration -q
uv run python -m scripts.check_compatibility
```

```powershell
uv run pytest tests/unit -q
uv run pytest tests/integration -q
uv run python -m scripts.export_contracts --check
```

集成测试使用真实 `technologyagent_test_*` 数据库和真实 replica set 事务，不使用 mock 代替事务。测试结束只删除带前缀的测试库。

## 本机监听与来源边界（P00-F01）

- 前端 dev/start 只绑定 `127.0.0.1`；API 也绑定 `127.0.0.1`。
- Uvicorn 以 `--no-proxy-headers` 启动，`request.client` 使用真实 socket peer，不采信客户端 `X-Forwarded-For/Host`。
- 本地会话要求回环 peer；Host 必须属于 `127.0.0.1/localhost/[::1]` + 配置的 `API_PORT` 或 `FRONTEND_PORT`（Next rewrite 可能保留前端 Host，也可能改写为后端目标）。
- 若请求带 `Origin`，必须是 `http://127.0.0.1|localhost|[::1]:FRONTEND_PORT`；不带 Origin 的本机脚本按明确规则允许。跨源浏览器 Origin、非本机 Host、非回环 peer 均返回 `LOCAL_SESSION_DISABLED/403`。
- Cookie 使用 `HttpOnly`、`SameSite=Strict`、`Path=/`，仅用于本机开发；生产身份认证是 P09 前条件。

## 错误与边界

- 数据库不可用时应用仍启动，`/health` 返回 200，`/ready` 返回 503，页面显示错误而不是无限加载。
- 本地会话只用于本机开发；非 `local` 模式、非回环 peer、Host/Origin 不匹配返回 403。
- P03 的 `/ready` 报告 model fake/configured/unavailable 与 MCP 端口可达性；fake 结果不能标成 live。
- P03 的 `/chat` 使用 Inject 的 GraphExecutor；live 工具调用走 MCP Bearer token，fake 走本地只读 registry。
- P02 增加 `threads`、`runs`、`messages`、`events` collection；启动时把遗留 created/running 标 failed/PROCESS_RESTARTED，释放 thread；P02 无 checkpoint 恢复。
- P01 增加 `parts`、`suppliers`、`quotes`、`inventories`、`drafts`、`orders` collection；默认 seed 只补齐缺失的固定合成记录，不覆盖任何已有记录/version/用户订单；`--reset` 只允许 `technologyagent_test_*`。
- P01 业务 API 需要本地会话；数据源统一标记为 `local_seed`，scope 为 `shared_catalog`。金额保持整数分，页面只展示。
- P02/P03 聊天 API 需要本地会话；事件先持久化再观察；同 thread 单活跃 run，request_id 幂等，跨 owner 返回 404。P03 不提供订单/审批工具。
- 模型 60s、工具 15s、活跃 180s，模型 20 次、工具 30 次；工具失败/超时返回可解释错误，不伪成功。

## P04 订单草稿与审批

- `/api/order-workflows` 与 `/api/runs/{id}/resume` 在 Mongo checkpointer 上延续同一 run；waiting_input 保留 interrupt 和草稿版本。
- `/api/drafts`、`PATCH /api/drafts/{id}` 以服务端报价计算金额，保留库存版本和报价快照；编辑 supersede 旧审批。
- `/api/orders/create` 只接 draft_id/approval_id/idempotency_key；订单、inbound、审批消费和成功 operation 在单个 Mongo 事务提交。
- `/api/operations/{id}/reconcile` 只读核对结果；处理中不重复写，过期空操作允许原幂等请求重新认领。
- 回归：`uv run pytest tests/integration/test_drafts.py tests/integration/test_checkpoint_resume.py tests/integration/test_order_idempotency.py tests/integration/test_mcp_tools.py -q`。
