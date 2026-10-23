# 阶段交付状态

更新时间：2026-10-23。P00与P00-F01/F02已交付，本轮独立复核可关闭原两项问题；P01初始交付与phase-p01已核对，但独立审查发现待补修项。P02–P09未开始。

| 阶段 | 实施状态 | 验证状态 | 远程交付 |
|---|---|---|---|
| 初始工程规划 | 规格、布局、扩展、Git规则已编写 | 文档检查通过 | 已推送main：8453859614cf00def940e7ba6f0ac90845d937d4 |
| 其他Agent详细实施计划 | 手册、接口、10阶段任务计划与启动提示词已编写 | 文档覆盖/衔接/链接检查通过 | 已推送main：823a8e3（以远程为准） |
| P00 | 已完成 T01–T05：可运行 FastAPI/Next.js、Mongo replica set 事务、配置与本地会话、启停与验证入口；F01/F02 补修已交付 | offline_verified + browser_verified + ci_verified + fix1_offline_verified + fix1_ci_verified；31 integration + 2 frontend tests；真实 Next→Uvicorn 链；Chrome 截图 | 已推送 main：ce66bfb（实现）、1d1acb9（CI 修复）、59d98e3（fix1）；phase-p00=419ab23 不变；fix1 CI run 39959955218 success；phase-p00-fix1 指向最终记录提交，SHA 以远程为准 |
| P01 | T01–T06初始实现已交付；本轮R01–R04补修待实施 | 原验收通过；本轮offline再次9/9通过，25 unit + 49 integration + 4 frontend；新增探针发现seed保护、数据对账与前端状态问题 | 实现5699197；CI run39966870327 success；phase-p01解引用232826336d29c19decf808c757cd0658536a8d02已核对，不移动 |
| P02 | not_started | not_run | not_delivered |
| P03 | not_started | not_run | not_delivered |
| P04 | not_started | not_run | not_delivered |
| P05 | not_started | not_run | not_delivered |
| P06 | not_started | not_run | not_delivered |
| P07 | not_started | not_run | not_delivered |
| P08 | not_started | not_run | not_delivered |
| P09 | not_started | not_run | not_delivered |

当前仓库已有 P00 工程底座和 P01 本地业务数据：页面、/health、/ready、真实 MongoDB 事务、本地会话，以及只读库存/供应商/报价查询与确定性补货预览。**尚不能**进行智能对话、调用真实模型、创建/修改订单、使用 MCP 产品服务、专家、技能或沙箱。P01 的 model/mcp/sandbox 在 /ready 中明确为 disabled。

当前下一步先执行[P01补修计划](../implementation/P01-followup.md)，复核后再进入[P02实施计划](../implementation/P02-implementation.md)与[P02 spec](../specs/P02-chat-streaming.md)，不自动开始P02。

## P01与前置阶段独立复核（2026-10-23）

对2328263运行`verify_stage P01 --mode offline --report .runtime/reports/P01-review-offline.json`，9/9通过、exit0，约222.3秒，含P00真实代理链与A/B构建回归。原P00-R01/R02可关闭。

P01新增复现：默认seed将I001 inbound65/version2覆盖回10/version1、O001 shipped回submitted；fixture有7件无未收订单支撑的inbound且额外两条预警；预览旧响应/选择可失配；首次会话失败后刷新不重试。详见[审查报告](../reviews/2026-10-23-P01-review.md)。这些修复尚未实施，现有测试通过不等于新增问题已关闭。

## 规划者独立复核（2026-10-23）

对419ab23重新执行P00 offline，6/6检查通过（23集成、2前端、构建等）；该提交GitHub Actions run39954200129成功。另发现原检查未覆盖的两项问题：本机前端监听/代理来源边界，以及修改API_PORT后使用旧构建的代理目标。后者已用隔离服务复现。

**P00-F01/F02本轮独立复核已通过，原两项问题关闭。** 证据见[P00-fix1](../../evidence/P00-fix1.md)和本次P01审查报告；原phase-p00不移动，修复交付使用phase-p00-fix1。当前待处理的是P01新增问题。

## P01 实际检查（2026-10-23）

- `uv run python -m scripts.seed --reset` 与再次 seed 均 exit 0；6/3/8/8/2/2 不翻倍；用户新增订单保留；manifest hash `670e478c…`。
- `uv run pytest tests/unit -q` exit 0，**25 passed**；`uv run pytest tests/integration -q` exit 0，**49 passed**。
- `uv run python -m scripts.verify_stage P01 --mode offline --report .runtime/reports/P01-offline.json` exit 0，9/9 checks，84.20s；`contract_check` exit 0。
- 前端 typecheck/test/build exit 0，4 前端测试 passed；`/data` 生成。
- Chrome headless：W01/名称筛选、W02 切换、7 天预览 Q01/55/66000、价格优先 Q02/55/60500；数据源 local_seed；页面无横向溢出；Cookie Strict。
- P01-A01..A06 全部通过；异常边界（422/404/空结果/缺失报价/缺失库存/非法库存/布尔金额）有测试。
- 未运行：真实模型、聊天、订单写入、MCP 产品、沙箱、ERP、Playwright E2E；P01 明确不实现。
- GitHub Actions P01 run [39966870327](https://github.com/newerwell/technologyagent/actions/runs/39966870327) 全部步骤 success；phase-p01 标签在最终记录提交后核对。

完整命令、退出码、截图和限制见 [evidence/P01.md](../../evidence/P01.md)。

## P00-F01/F02 补修结果（2026-10-23）

- **F01**：Next dev/start 与 API 均只监听 127.0.0.1；Uvicorn 加 `--no-proxy-headers`；本地会话增加回环 peer + Host 白名单 + 前端 Origin 白名单；Cookie 统一 SameSite=Strict。
- **真实链路**：`uv run pytest tests/integration/test_local_startup_boundary.py -q` exit 0，1 passed；真实 Uvicorn + Next dev 下正常会话可创建/读取；恶意 Origin、伪造 Host、非回环 peer 均 403；`X-Forwarded-For` 不改变 peer；本机非回环 IPv4 连接 3130/8130 均失败。
- **F02**：`start.ps1` 每次新启动前端都按当前 API_PORT 构建，构建目标写入 `.runtime/frontend-build.json`；启动成功必须通过经前端的同源 `/health` 与 `/ready`；配置变化未停旧进程时拒绝启动。
- **构建 A/B**：`uv run pytest tests/integration/test_startup_configuration.py -q` exit 0，3 passed；两次构建的 rewrite 分别指向 A/B API_PORT。
- **启动 A/B**：API 8130→8131、前端 3130：两次启动 exit 0；同源 health/ready 通过；B 的 routes-manifest 指 8131，直连 8130 失败；同配置重复启动进程数仍 2；运行中改端口被拒绝；停止后端口关闭、marker 删除、测试库删除。
- **全量**：`uv run pytest tests/integration -q` exit 0，**31 passed**。
- **Chrome**：默认端口 + 测试库打开页面 200；local-owner 会话建立；Cookie HttpOnly/**SameSite=Strict**；仅未登录 401 控制台记录。
- fix1 commit `59d98e3` 已推送；GitHub Actions run [39959955218](https://github.com/newerwell/technologyagent/actions/runs/39959955218) success；旧 phase-p00=419ab23 保持不变；phase-p00-fix1 指向最终记录提交。

## P00 实际检查

- `uv sync --frozen --group dev` exit 0；`npm --prefix frontend ci` exit 0。
- `uv run python -m scripts.init_db` 连续两次 exit 0；replica set `ta-rs`、primary=true、schema_version=1。
- `uv run python -m scripts.check_compatibility` exit 0；8/8 探针通过（FastAPI/LangGraph/假 tool loop/ChatOpenAI 构造/Mongo 事务/Mongo checkpointer/FastMCP HTTP/DeepAgents 假图）。
- `uv run pytest tests/integration -q`：23 passed，exit 0；事务测试使用真实 replica set，不使用 mock。
- `npm --prefix frontend run typecheck`、`run test -- --run`（2 passed）、`run build` 均 exit 0。
- `uv run python -m scripts.verify_stage P00 --mode offline --report .runtime/reports/P00-offline.json` exit 0；6/6 checks passed。
- Chrome headless 打开 3030：页面显示后端已连接、就绪、local-owner 会话；原验收 Cookie 为 HttpOnly/SameSite=Lax，P00-F01 起统一为 **Strict**。DB 停止后 /ready 503，页面显示“降级/不可用/会话不可用”，保留“重新检测”，不无限 loading。
- `start.ps1` 在项目目录和另一个工作目录各运行一次：第二次不重复开进程；`stop.ps1` 后 8030/3030 均关闭。
- GitHub Actions `.github/workflows/ci.yml`：run [39953759929](https://github.com/newerwell/technologyagent/actions/runs/39953759929) 全部步骤 success；首轮 run 39950310945 在 init_db 失败，已由 `1d1acb9` 改用 compose 启动 Mongo 并修复。
- 未验证项：Playwright E2E 未运行（P02 起）；真实模型/MCP 产品/沙箱/ERP 未实现，分别属 P03/P06/P08。

完整命令、退出码、环境、截图路径与已知限制见 [evidence/P00.md](../../evidence/P00.md)。

## 规划基线检查（历史）

初始规划阶段已执行：19个Markdown文档读取与相对链接检查通过；10个阶段均包含Git交付清单及对应phase-pxx标签；配置、依赖、运行目录的Git忽略规则检查通过。该检查只证明文档结构，不证明产品功能。

P00 交付时补充执行：`docker compose config` exit 0、CI YAML 解析 exit 0、`git diff --check` exit 0，并审查暂存路径排除 `.env`、`.runtime`、`mongo-data`、`node_modules`、`.next`、`.dsh-meow`。
