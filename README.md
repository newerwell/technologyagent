# TechnologyAgent

[![ci](https://github.com/newerwell/technologyagent/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/newerwell/technologyagent/actions/workflows/ci.yml)

从零实现的采购 Agent 项目。业务目标是查询库存和供应商、生成补货建议、确认后执行订单，并逐步支持流程评审、图表报告、专家委派、技能记忆与 ERP 接入。

仓库：[newerwell/technologyagent](https://github.com/newerwell/technologyagent)。参考项目只提供需求和效果参考；本仓库独立编写实现、测试与文档。

## 当前状态

**P07-fix1实现已完成并通过本地offline与fake browser回归；严格阶段验收尚未关闭，P08未开始。** 本轮191 unit、169 integration、38 frontend与Chromium E2E 11/11通过；报告下载API字节/来源核验5/5通过。P03固定3题×3次及P07 live因显式启用/隔离数据库门槛未满足而`not_run`，没有发起真实模型请求。

本轮实现/验收入口：[P07-fix1证据](./evidence/P07-fix1.md)、[P07补修计划](./docs/implementation/P07-followup.md)与[独立审查](./docs/reviews/2026-10-25-P07-review.md)。现有CI run [40180805788](https://github.com/newerwell/technologyagent/actions/runs/40180805788) 的 `p06-offline` job success；它不是专用P07 job。旧phase-p07→307edb4、phase-p03→7f69ff1等标签保持不动；live和新P03 3×3验收通过后才可创建补修标签。

HTML展示由用户确认，其他正式下载/报告打开边界按原证据记录。P08–P09未开始。

## 快速启动（Windows）

```powershell
# 1. 安装依赖（首次；需要 uv、Node.js、Docker）
uv sync --frozen --group dev
npm --prefix frontend ci
uv run python -m scripts.seed

# 2. 启动（自动启动 Mongo replica set、MCP、初始化索引、API 与前端）
.\start.ps1

# 页面 http://127.0.0.1:3030
# 对话 http://127.0.0.1:3030/chat
# 业务数据 http://127.0.0.1:3030/data
# API  http://127.0.0.1:8030/health
# MCP  http://127.0.0.1:9030/health
# 停止
.\stop.ps1
```

配置模板见 `.env.example`。默认端口 3030/8030/9030/27027，均可通过环境变量或 `.env` 修改。

## 检查

```powershell
uv run pytest tests/unit -q
uv run pytest tests/integration -q
uv run python -m scripts.export_contracts --check
uv run python -m scripts.check_compatibility
uv run python -m scripts.verify_stage P03 --mode offline --report .runtime/reports/P03-offline.json
# 浏览器：先启动 3030/8030/9030，再运行
uv run python -m scripts.verify_stage P03 --mode browser --report .runtime/reports/P03-browser.json
npm --prefix frontend run typecheck
npm --prefix frontend run test -- --run
npm --prefix frontend run build
```

实际结果、未运行项和已知限制见 [evidence/P03.md](./evidence/P03.md)、[evidence/P02-fix1.md](./evidence/P02-fix1.md)、[evidence/P02.md](./evidence/P02.md)；阶段状态见 [STATUS](./docs/delivery/STATUS.md)。

## 阅读顺序

1. [整体文件布局](./docs/architecture/PROJECT_LAYOUT.md)：目录、模块责任、每个文件的创建阶段。
2. [扩展设计](./docs/architecture/EXTENSION_GUIDE.md)：依赖方向、稳定接口、未来功能接入方式。
3. [阶段总览](./docs/specs/README.md)与[共享契约](./docs/specs/CONTRACTS.md)：产品行为、数据和接口标准。
4. [阶段Git交付规则](./docs/delivery/GIT_WORKFLOW.md)：每阶段验收、提交、推送与远程核对。
5. [交付状态](./docs/delivery/STATUS.md)：当前阶段与实际验证范围。
6. [其他Agent实施入口](./docs/implementation/README.md)：10份详细实施计划、统一接口、检查命令与可复制启动提示词。

P04 验收后形成采购核心 MVP，P09 本地验收后具备与参考项目相近的完整本地演示能力。真实 ERP 联调单独记录。
