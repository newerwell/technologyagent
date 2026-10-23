# backend 后端应用

## 职责

P01 的 FastAPI 应用提供工程底座与本地只读业务：配置、统一响应/错误、健康与就绪、MongoDB 事务、localhost 会话，以及合成库存/供应商/报价查询和确定性补货预览。它**不包含**聊天、真实模型、订单执行、专家或沙箱能力。

## 目录

```text
backend/app/
├─ main.py                 # 应用组装、中间件、异常转换、生命周期
├─ config.py               # Settings / load_settings / 密钥脱敏
├─ bootstrap.py            # Container 与依赖组装
├─ contracts/
│  ├─ common.py            # Envelope、Page、AppError、RequestContext、Clock
│  ├─ domain.py            # P01 实体、查询请求与预览模型
│  └─ domain-schema.v1.json # 由脚本生成的稳定 JSON Schema
├─ api/
│  ├─ health.py            # GET /health、GET /ready
│  ├─ session.py           # POST /api/session/local、GET /api/session/me
│  ├─ catalog.py           # /api/parts、/api/suppliers、/api/quotes
│  ├─ inventory.py         # /api/inventory、warnings、summary、preview
│  └─ dependencies.py      # 容器注入、请求 ID、Cookie 身份解析
├─ domain/                 # 纯函数金额、库存状态与补货规则
├─ ports/                  # CatalogReader / InventoryReader Protocol
├─ repositories/
│  ├─ mongo.py             # AsyncMongoClient、真实事务上下文
│  ├─ indexes.py           # collection 约定、schema_version=1、幂等索引
│  ├─ sessions.py          # 会话摘要持久化
│  ├─ catalog.py           # 零件/供应商/报价读取
│  └─ inventory.py         # 库存筛选/分页/范围读取
├─ services/
│  ├─ sessions.py          # 随机 token + HMAC 摘要 + 24h 过期
│  ├─ readiness.py         # ping/primary/事务回滚探针
│  ├─ seeding.py           # fixtures 校验、manifest 与幂等 seed
│  ├─ catalog.py           # 目录/库存查询与展示派生值
│  └─ replenishment.py     # 补货预览用例
└─ README.md
```

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
- P00 的 `/ready` 始终把 model/mcp/sandbox 标为 disabled，因为对应实现尚未交付。
- P01 增加 `parts`、`suppliers`、`quotes`、`inventories`、`drafts`、`orders` collection；默认 seed 只补齐缺失的固定合成记录，不覆盖任何已有记录/version/用户订单；`--reset` 只允许 `technologyagent_test_*`。
- P01 业务 API 需要本地会话；数据源统一标记为 `local_seed`，scope 为 `shared_catalog`。金额保持整数分，页面只展示。
