# 阶段交付状态

更新时间：2026-10-23。P00 已实施并通过离线/Chrome 浏览器验收；P01–P09 未开始。

| 阶段 | 实施状态 | 验证状态 | 远程交付 |
|---|---|---|---|
| 初始工程规划 | 规格、布局、扩展、Git规则已编写 | 文档检查通过 | 已推送main：8453859614cf00def940e7ba6f0ac90845d937d4 |
| 其他Agent详细实施计划 | 手册、接口、10阶段任务计划与启动提示词已编写 | 文档覆盖/衔接/链接检查通过 | 已推送main：823a8e3（以远程为准） |
| P00 | 已完成 T01–T05：可运行 FastAPI/Next.js、Mongo replica set 事务、配置与本地会话、启停与验证入口 | offline_verified + browser_verified + ci_verified；23 integration + 2 frontend tests；Chrome 截图 | 已推送 main：ce66bfb（实现）、1d1acb9（CI 修复）；GitHub Actions success；phase-p00 指向最终记录提交，SHA 以远程为准 |
| P01 | not_started | not_run | not_delivered |
| P02 | not_started | not_run | not_delivered |
| P03 | not_started | not_run | not_delivered |
| P04 | not_started | not_run | not_delivered |
| P05 | not_started | not_run | not_delivered |
| P06 | not_started | not_run | not_delivered |
| P07 | not_started | not_run | not_delivered |
| P08 | not_started | not_run | not_delivered |
| P09 | not_started | not_run | not_delivered |

当前仓库已有可运行的 P00 工程底座：页面、/health、/ready、真实 MongoDB 事务探针和本地会话。**尚不能**查询采购业务、调用真实模型、创建订单、使用 MCP 产品服务、专家、技能或沙箱。P00 的 model/mcp/sandbox 在 /ready 中明确为 disabled。

下一实施入口为 [P01 实施计划](../implementation/P01-implementation.md) 与 [P01 spec](../specs/P01-domain-data.md)，不自动开始 P01。

## P00 实际检查

- `uv sync --frozen --group dev` exit 0；`npm --prefix frontend ci` exit 0。
- `uv run python -m scripts.init_db` 连续两次 exit 0；replica set `ta-rs`、primary=true、schema_version=1。
- `uv run python -m scripts.check_compatibility` exit 0；8/8 探针通过（FastAPI/LangGraph/假 tool loop/ChatOpenAI 构造/Mongo 事务/Mongo checkpointer/FastMCP HTTP/DeepAgents 假图）。
- `uv run pytest tests/integration -q`：23 passed，exit 0；事务测试使用真实 replica set，不使用 mock。
- `npm --prefix frontend run typecheck`、`run test -- --run`（2 passed）、`run build` 均 exit 0。
- `uv run python -m scripts.verify_stage P00 --mode offline --report .runtime/reports/P00-offline.json` exit 0；6/6 checks passed。
- Chrome headless 打开 3030：页面显示后端已连接、就绪、local-owner 会话；Cookie HttpOnly/SameSite=Lax。DB 停止后 /ready 503，页面显示“降级/不可用/会话不可用”，保留“重新检测”，不无限 loading。
- `start.ps1` 在项目目录和另一个工作目录各运行一次：第二次不重复开进程；`stop.ps1` 后 8030/3030 均关闭。
- GitHub Actions `.github/workflows/ci.yml`：run [39953759929](https://github.com/newerwell/technologyagent/actions/runs/39953759929) 全部步骤 success；首轮 run 39950310945 在 init_db 失败，已由 `1d1acb9` 改用 compose 启动 Mongo 并修复。
- 未验证项：Playwright E2E 未运行（P02 起）；真实模型/MCP 产品/沙箱/ERP 未实现，分别属 P03/P06/P08。

完整命令、退出码、环境、截图路径与已知限制见 [evidence/P00.md](../../evidence/P00.md)。

## 规划基线检查（历史）

初始规划阶段已执行：19个Markdown文档读取与相对链接检查通过；10个阶段均包含Git交付清单及对应phase-pxx标签；配置、依赖、运行目录的Git忽略规则检查通过。该检查只证明文档结构，不证明产品功能。

P00 交付时补充执行：`docker compose config` exit 0、CI YAML 解析 exit 0、`git diff --check` exit 0，并审查暂存路径排除 `.env`、`.runtime`、`mongo-data`、`node_modules`、`.next`、`.dsh-meow`。
