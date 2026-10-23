# P00：工程底座与兼容性基线

状态：已实施；离线与 Chrome 浏览器验收通过；远程交付状态以 `docs/delivery/STATUS.md` 为准。依赖：初始工程蓝图已提交至目标仓库。目标：在独立technologyagent项目中从零创建空应用，依赖故障可定位，后续阶段有稳定目录和契约。

## 任务

- [x] **P00-T01 按完整蓝图创建项目骨架。** 先读`docs/architecture/PROJECT_LAYOUT.md`与`EXTENSION_GUIDE.md`，确定全部阶段的归属、依赖方向和扩展接口；只创建P00需要的目录与代码，后续目录保留在蓝图中。前端展示项目名和后端状态；后端提供/health。交付：`frontend/`、`backend/app/main.py`、`backend/app/api/health.py`及模块README。检查：页面可打开，health返回200，不从参考项目复制实现。
- [x] **P00-T02 锁定依赖。** 依据参考组合选择可安装版本，验证 FastAPI、模型适配、LangGraph checkpointer、FastMCP 客户端的导入和最小调用；DeepAgents 先做离线组装兼容检查，不引入产品执行能力。交付：Python 锁文件、前端 lockfile、`scripts/check_compatibility.py`；记录实际 Python/Node/包版本，不复制宽松版本范围充当锁定。
- [x] **P00-T03 配置 MongoDB 与数据访问。** `compose.yaml` 提供单节点replica set并初始化，`repositories/mongo.py` 管连接和关闭；执行跨两个测试collection写入/回滚探针，确认事务可用；/ready 检查primary与事务能力，失败返回503。约定collection名、索引初始化入口和schema_version=1。
- [x] **P00-T04 本地身份与配置。** 完成 localhost 开发会话，固定 owner 不由前端输入；集中定义 API、DB、模型与 MCP 配置，提交 `.env.example`，缺少 Key 时页面和历史仍可用，真实智能对话明确不可用。
- [x] **P00-T05 启停与证据。** start.ps1 从脚本目录定位项目、按顺序启动、检查端口占用；stop.ps1 只关闭本项目登记进程。创建 `evidence/P00.md`，写明端口、依赖、操作方法和失败记录。

## 验收

| ID | 操作 | 通过条件 |
|---|---|---|
| P00-A01 | 从项目目录和另一个工作目录调用启动脚本 | 两次都能定位同一项目，不额外启动重复实例 |
| P00-A02 | 打开浏览器页面；请求 /health、/ready | 页面可见；健康状态与依赖实际情况一致 |
| P00-A03 | 事务探针通过后，关闭数据库查询ready | 探针回滚无残留；数据库关闭后503、db unavailable，页面不无限加载 |
| P00-A04 | 移除模型 Key，重新启动 | 基础页面仍可用；model 状态为 disabled，响应不含密钥 |
| P00-A05 | 前端构建和兼容检查 | 退出码 0；版本与命令写入 evidence |

验收结果（2026-10-23，本机 Windows 10）：A01–A05 全部通过。实际命令、退出码、事务与浏览器证据见 [evidence/P00.md](../../evidence/P00.md)。

## 本阶段结束后

得到可启动空壳，尚不能查询业务或调用模型。下一阶段依赖 MongoDB 连接、配置、身份和统一响应契约；不提前制作沙箱池或多 Agent。

## 阶段 Git 交付

- [ ] 实现和本阶段验收完成；新增/变更模块包含中文README，说明职责、接口、运行例子与限制。
- [ ] 更新本阶段evidence、任务勾选、架构图和扩展契约；检查改动及敏感文件，仅暂存本阶段明确路径。
- [ ] 提交本阶段源码、测试、文档和证据，推送到 `origin/main`；创建并推送 `phase-p00` 标签；按 `docs/delivery/GIT_WORKFLOW.md` 核对远程SHA。
- [ ] 向用户报告结果、实际检查、commit链接及阶段标签。推送未成功则标记“远程未交付”，不宣布阶段完成。
