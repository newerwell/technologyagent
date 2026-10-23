# backend 后端应用

## 职责

P00 的 FastAPI 应用只负责工程底座：配置加载、统一响应/错误、健康与就绪检查、MongoDB 连接与事务边界、localhost 开发会话。它**不包含**采购业务、聊天、真实模型、订单、专家或沙箱能力。

## 目录

```text
backend/app/
├─ main.py                 # 应用组装、中间件、异常转换、生命周期
├─ config.py               # Settings / load_settings / 密钥脱敏
├─ bootstrap.py            # Container 与依赖组装
├─ contracts/common.py     # Envelope、AppError、RequestContext、Clock
├─ api/
│  ├─ health.py            # GET /health、GET /ready
│  ├─ session.py           # POST /api/session/local、GET /api/session/me
│  └─ dependencies.py      # 容器注入、请求 ID、Cookie 身份解析
├─ repositories/
│  ├─ mongo.py             # AsyncMongoClient、真实事务上下文
│  ├─ indexes.py           # collection 约定、schema_version=1、幂等索引
│  └─ sessions.py          # 会话摘要持久化
├─ services/
│  ├─ sessions.py          # 随机 token + HMAC 摘要 + 24h 过期
│  └─ readiness.py         # ping/primary/事务回滚探针
└─ README.md
```

## 公开接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /health | 只表示进程存活，不检查依赖，不泄露配置 |
| GET | /ready | db/primary/事务/model/mcp/sandbox 状态；数据库不可用返回 503 |
| POST | /api/session/local | 仅 APP_MODE=local 且回环来源；请求体 owner_id 被忽略 |
| GET | /api/session/me | 需要 Cookie；返回服务端解析的 owner_id |

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
.\start.ps1
```

单独启动 API：

```powershell
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8030
```

## 测试

```powershell
uv run pytest tests/integration -q
uv run python -m scripts.check_compatibility
```

集成测试使用真实 `technologyagent_test_*` 数据库和真实 replica set 事务，不使用 mock 代替事务。测试结束只删除带前缀的测试库。

## 错误与边界

- 数据库不可用时应用仍启动，`/health` 返回 200，`/ready` 返回 503，页面显示错误而不是无限加载。
- 本地会话只用于本机开发；非 `local` 模式或非回环来源返回 403。生产身份认证是 P09 前条件。
- P00 的 `/ready` 始终把 model/mcp/sandbox 标为 disabled，因为对应实现尚未交付。
- P00 只初始化 `sessions`、`system_meta`、`_health_probe` 三个 collection，不提前创建业务 collection。
