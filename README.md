# TechnologyAgent

[![ci](https://github.com/newerwell/technologyagent/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/newerwell/technologyagent/actions/workflows/ci.yml)

从零实现的采购 Agent 项目。业务目标是查询库存和供应商、生成补货建议、确认后执行订单，并逐步支持流程评审、图表报告、专家委派、技能记忆与 ERP 接入。

仓库：[newerwell/technologyagent](https://github.com/newerwell/technologyagent)。参考项目只提供需求和效果参考；本仓库独立编写实现、测试与文档。

## 当前状态

**P00 工程底座与 P01 本地业务数据已实现。** 可启动 FastAPI + Next.js + MongoDB 单节点 replica set，查看健康/就绪、真实事务、本地会话，并在 `/data` 查询合成库存/供应商/报价、运行确定性补货预览。P00-F01/F02 补修已交付；P02–P09 尚未实施。

最新复核：P00原两项问题已关闭；P01现有自动检查通过，但初始化数据保护、在途对账和前端状态尚有待修问题。当前先交付[P01补修](./docs/implementation/P01-followup.md)，再进入P02；[检查报告](./docs/reviews/2026-10-23-P01-review.md)区分了实际通过项和新增缺口。

当前**不能**进行智能对话、调用真实模型、创建/修改订单、使用专家/技能或沙箱；这些能力在后续阶段实现。P01 只读业务页面见 `/data`。规划文档和阶段验收记录见 `docs/` 与 `evidence/`。

## 快速启动（Windows）

```powershell
# 1. 安装依赖（首次；需要 uv、Node.js、Docker）
uv sync --frozen --group dev
npm --prefix frontend ci
uv run python -m scripts.seed

# 2. 启动（自动启动 Mongo replica set、初始化索引、启动 API 与前端）
.\start.ps1

# 页面 http://127.0.0.1:3030
# 业务数据 http://127.0.0.1:3030/data
# API  http://127.0.0.1:8030/health
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
uv run python -m scripts.verify_stage P01 --mode offline --report .runtime/reports/P01-offline.json
npm --prefix frontend run typecheck
npm --prefix frontend run test -- --run
npm --prefix frontend run build
```

实际结果、未运行项和已知限制见 [evidence/P01.md](./evidence/P01.md)、[evidence/P00.md](./evidence/P00.md)；阶段状态见 [STATUS](./docs/delivery/STATUS.md)。

## 阅读顺序

1. [整体文件布局](./docs/architecture/PROJECT_LAYOUT.md)：目录、模块责任、每个文件的创建阶段。
2. [扩展设计](./docs/architecture/EXTENSION_GUIDE.md)：依赖方向、稳定接口、未来功能接入方式。
3. [阶段总览](./docs/specs/README.md)与[共享契约](./docs/specs/CONTRACTS.md)：产品行为、数据和接口标准。
4. [阶段Git交付规则](./docs/delivery/GIT_WORKFLOW.md)：每阶段验收、提交、推送与远程核对。
5. [交付状态](./docs/delivery/STATUS.md)：当前阶段与实际验证范围。
6. [其他Agent实施入口](./docs/implementation/README.md)：10份详细实施计划、统一接口、检查命令与可复制启动提示词。

P04 验收后形成采购核心 MVP，P09 本地验收后具备与参考项目相近的完整本地演示能力。真实 ERP 联调单独记录。
