# 采购 Agent 分阶段 Spec

编写日期：2026-10-23。状态：P00 与 P01 已实施并完成本地规则/API/UI 与浏览器验收；P01-fix1 已推送并通过 CI，等待标签核对/复核；P02–P09 仍为设计稿，任务未实施、验收未执行。

## 目标与使用方法

从零实现一个与当前 `ERP-AGENT` 思路相近的采购助手：自然语言查询业务数据，生成有依据的采购建议，确认后执行订单操作，展示执行过程，支持报告、子 Agent、技能、记忆及故障恢复。

用户已明确要求：**独立新建、从零重写，不在 ERP-AGENT 上继续修改；每个阶段完成并验收后都要提交并推送 GitHub；工程开始前确定整体文件分布及扩展位置。** 目标仓库为 https://github.com/newerwell/technologyagent.git，新项目本地根目录为工作区中的 `technologyagent/`。ERP-AGENT只作业务与效果参考，不复制其实现、配置、密钥、数据或Git历史。

业务场景延续摩托车零部件采购。P00 已落地可运行工程底座，P01 已落地本地合成数据、查询与确定性补货；P02 起尚未实施。后续唯一生效规格为新仓库 `docs/specs/`；工作区 `mvp-specs/` 为本次规划导出副本，实施时不在两处重复维护。

先读新仓库的 `docs/architecture/PROJECT_LAYOUT.md` 和 `docs/architecture/EXTENSION_GUIDE.md`，了解完整文件布局、创建阶段、模块接口与依赖方向；阶段提交规则见新仓库 `docs/delivery/GIT_WORKFLOW.md`。这些工程约束适用于所有阶段。

用户选用其他Agent写代码，本聊天只做规划。实施者下一步阅读[详细实施入口](../implementation/README.md)，每阶段有与本spec任务编号对应的implementation计划，含文件、方法、步骤、测试断言和交付命令；可复制[启动提示词](../implementation/AGENT-PROMPTS.md)开始。

先读 [共享契约](./CONTRACTS.md)，再按 P00 → P09 执行。每阶段任务和验收完成后，还必须提交并推送到origin/main，核对远程分支包含该阶段提交并创建阶段标签，才可宣布本阶段交付完成。阶段边界内允许调整内部实现，跨阶段的字段和接口变更要同步修改契约、调用方及测试。

| 阶段 | 完成后用户能得到什么 | 前置依赖 | 定位 |
|---|---|---|---|
| [P00 工程底座](./P00-foundation.md) | 在本机启动前后端和数据库，看到明确健康状态 | 无 | 可运行空壳 |
| [P01 业务数据](./P01-domain-data.md) | 查看库存、供应商、报价，计算可复现的补货建议 | P00 | 不依赖模型的业务基础 |
| [P02 对话与历史](./P02-chat-streaming.md) | 流式对话、停止任务、刷新恢复历史与运行状态 | P01 | 可用交互外壳 |
| [P03 Agent 与 MCP](./P03-agent-tools.md) | 用真实模型调用业务工具，回答有数据依据的问题 | P02 | 只读智能助手 |
| [P04 订单确认与恢复](./P04-orders-approval.md) | 补充字段、修改草稿、确认下单、重启后继续审批 | P03 | 核心 MVP 完成 |
| [P05 规划执行与评审](./P05-harness-review.md) | 看到任务计划、执行阶段和有界纠错过程 | P04 | 可检查的工作流 |
| [P06 图表报告与沙箱](./P06-artifacts-sandbox.md) | 生成并下载图表、采购报告，隔离执行分析代码 | P05 | 可交付分析结果 |
| [P07 子 Agent、技能与记忆](./P07-specialists-skills-memory.md) | 按任务分工，使用采购技能，跨会话记住显式偏好 | P06 | 扩展能力接近参考项目 |
| [P08 完整业务工具与 ERP](./P08-erp-integration.md) | 使用四类业务工具，按配置切换本地或 ERP 数据 | P07 | 业务范围接近参考项目 |
| [P09 综合验收与运行交付](./P09-acceptance-operations.md) | 稳定复现整套演示，定位故障，查看验收证据 | P08 | 可交付版本 |

**停靠点：** P03 可展示只读问答；P04 可交付核心 MVP；P06 可展示完整分析和订单闭环；P09 完成本地完整演示版。真实 ERP 的写入联调是独立验收项，未完成时只能宣称本地演示通过。

## 最终效果如何对应参考项目

| 参考能力与代码入口 | 对应阶段 | 本方案完成定义 |
|---|---|---|
| Next.js 对话、历史、工具卡片：`frontend/src/` | P02–P04 | 浏览器完成连续对话、工具展示、审批和历史恢复 |
| MCP 业务工具：`src/mcp_server/tools/` | P03、P08 | 四类 23 项工具均有 schema、实现或明确不支持结果、测试 |
| LangGraph / DeepAgents：`src/agent/main_agent.py` | P03–P07 | 模型真实调工具，检查点恢复，受控工作流和两类专家 |
| 人工中断：`config.py`、订单专家 YAML | P04 | 同意、拒绝、编辑、重启恢复、重复请求均有验证 |
| Harness 与 rubric：`harness.py`、`harness_config.yaml` | P05 | 结构化阶段、可判定评审、有限重做和终态 |
| 图表、文件与 Docker：`tools/`、`backends/` | P06 | 三类真实图表、四种报告、下载与容器异常处理 |
| Skills / Store：`src/skills/`、`mongodb_store.py` | P07 | 三个可验证技能、显式偏好持久化和隔离 |
| 外部 ERP：`http_base.py` | P08 | 映射与超时策略明确，真实读写证据单独记录 |
| 启停与调用限制：`start.ps1`、中间件 | P09 | 一键启停、限额、恢复、日志、全链路验收 |

相似结果按用户能完成的任务衡量，不以文件数量、框架中间件数量或工具总数充当完成标准。原项目 26 个图表名称不等于 26 种完整绘图实现；本方案先验收柱状、折线、饼图三种真实类型。

## 技术与路线选择

| 路线 | 优点 | 代价 | 本次取舍 |
|---|---|---|---|
| 裁剪参考仓库 | 可沿用现有交互 | 不满足用户独立重写要求 | 不采用 |
| 独立空仓库，从零实现，先规划结构再逐步增加能力 | 每阶段可运行、可解释、可验收 | 需要重新实现并验证各模块 | 用户指定路线 |
| 先完整搭建全部框架组件 | 结构一开始接近参考 | 首次可用时间长，定位问题困难 | 暂不采用 |

默认前端 Next.js / React / TypeScript，后端 Python / FastAPI，业务与会话存储 MongoDB，状态编排 LangGraph，P07 再接入 DeepAgents 的专家和技能能力，P06 引入 Docker 执行环境。MCP 使用 FastMCP 和适配器，具体传输与依赖版本在 P00 验证并锁定，不要求照搬旧 SSE 传输。保留一套 MongoDB，避免为练习阶段额外设计数据库迁移。

本机基线为 Windows、Python 3.11+、Node.js 20.9+；这些是参考项目基线，不保证任意未来依赖版本兼容。P00 必须以实际安装、构建与最小 API 验证生成锁文件。模型使用可配置的 OpenAI 兼容接口，不硬编码某个模型名称或密钥。

## 证据边界

本次依据参考项目 README、TECH_STACK、TOOLS、数据说明，以及主 Agent、订单工具、库存数据源、Harness、前端类型和专家 YAML 阅读整理；没有运行其业务流程。参考文档中的历史通过记录不是本方案的测试结果。参考项目库存当前使用本地快照，供应商、零件和订单仍依赖外部 ERP；本方案重新建立独立的本地演示数据。

每阶段新增 `evidence/Pxx.md`，记录环境、命令、退出码、期望与实际结果、截图/输出路径、真实模型与 ERP 是否启用。检查分为：静态检查、离线自动化、真实模型、浏览器交互、真实 ERP。只标记实际完成的类型。

## 官方依据

- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)：中断与恢复机制；应用层仍需保证业务写入幂等。
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)：检查点和跨会话 Store 分工。
- [MCP tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)：工具发现、输入 schema、结构化结果；此链接为指定版本规范，不当作最新版声明。
- [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview)：专家委派、文件与技能能力。具体 API 以 P00 锁定版本及 P07 兼容验证为准。
