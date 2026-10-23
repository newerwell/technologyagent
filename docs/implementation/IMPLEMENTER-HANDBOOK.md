# 实施统一约定

## 1. 每次接手的第一步

在仓库根执行`git status --short`、`git log -5 --oneline`、`git remote -v`，确认路径与origin确为technologyagent。读取AGENTS.md、当前阶段spec/plan、STATUS、上一阶段evidence；检查上一阶段标签解引用SHA。用户可能在另一台电脑实施，因此不硬编码规划者的C盘路径。

只实现用户指定阶段；前置阶段缺代码、必要验收未通过或远程未交付时，先准确报告具体缺项。用户若显式要求修复前置阶段，按修复范围提交，不重写全部工程。不复制参考ERP-AGENT源码或私有数据。

## 2. 统一技术和运行默认值

| 项目 | 默认选择 | 说明 |
|---|---|---|
| Python | 3.11+，uv管理，pyproject.toml + uv.lock | P00锁定实际兼容版本，不把宽泛版本范围当锁文件 |
| 后端 | FastAPI + Pydantic，异步服务方法 | 本地包导入backend.app，MCP也由根项目环境启动 |
| 数据库 | MongoDB replica set，PyMongo Async API | 应用用AsyncMongoClient，不新增Motor；框架checkpointer如需同步客户端单独封装，阻塞调用不得占用请求事件循环 |
| 前端 | Next.js/React/TypeScript，npm lock | 依赖版本P00实测，后续阶段不擅自升级整套框架 |
| 单元/集成 | pytest、pytest-asyncio、HTTPX | DB事务测试使用真replica set；内存替身不能证明事务 |
| 前端测试 | Vitest + Testing Library；Playwright用于E2E | P00配置命令，P02开始实际浏览器用例 |
| 地址 | frontend 3030，API 8030，MCP 9030，Mongo 27027 | 统一.env可改，不占用参考项目已用端口 |
| 模型 | MODEL_MODE=fake/live，MODEL_BASE_URL/MODEL_NAME/MODEL_API_KEY | 不提交Key；fake模式在UI及evidence明示 |
| MCP | Streamable HTTP，127.0.0.1:9030/mcp | P00探针锁定客户端/服务器兼容；P03才接业务 |

Mongo官方说明见[PyMongo Async迁移指南](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/reference/migration/)。此处只采用异步客户端接口选择，不宣称已测得性能提升。框架中断恢复语义见[LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)；恢复节点会重跑，业务写入仍需事务与幂等。

Mongo容器内部也监听27027，replica set名ta-rs，节点公布localhost:27027；端口映射仅127.0.0.1，宿主客户端配置replicaSet=ta-rs、directConnection=true。Python/FastAPI/MCP均在宿主运行，避免容器内外公布主机名不一致。未来全容器化部署另写连接方案，不沿用此localhost配置。

测试库前缀technologyagent_test_，开发库technologyagent_dev。测试和清理工具必须验证目标库前缀，不能删除开发库；持久运行目录为根目录.runtime与storage（已被Git排除）。

## 3. P00必须提供的执行命令

```powershell
uv sync --frozen --group dev
uv run python -m scripts.check_compatibility
uv run python -m scripts.init_db
uv run pytest tests/unit -q
uv run pytest tests/integration -q
npm --prefix frontend ci
npm --prefix frontend run typecheck
npm --prefix frontend run test -- --run
npm --prefix frontend run build
uv run python -m scripts.verify_stage P00 --mode offline
```

这些命令为未来接口，当前不可执行。P00没有unit目录测试时验证器只运行当阶段已定义测试，不把pytest退出码5当成功。P01以后真实存在的unit测试成为必跑项。E2E统一`npm --prefix frontend run test:e2e -- --project=chromium`，配置testDir指向仓库tests/e2e。所有进程调用保存退出码；PowerShell上一条失败不得被最后一条成功掩盖。

verify_stage参数：`P00..P09 --mode offline|live|browser --report .runtime/reports/Pxx-<mode>.json`。默认offline按阶段manifest运行已存在的检查；报告保存命令、退出码、耗时、skip及原因。live先检查Key/环境，缺失标not_run，不能返回“live通过”。browser无可用浏览器时同理。离线报告成功只表示offline检查完成，最终阶段是否通过还看spec的必需live/browser条件。

CI用同一manifest；集成测试用Mongo service replica set。P06以前不要求Docker沙箱；P06容器集成另有明确检查组。没有模型/ERP凭证的CI不调用收费或真实写接口。

## 4. 类型、错误与归属

跨层签名见[INTERFACES](./INTERFACES.md)。Python类/DTO可定义于具名模块，示意签名不是整段实现代码。禁止API和MCP各自计算金额、补货或批准写入。公开函数写类型注解，私有实现由实施者决定。

业务异常统一AppError(code,message,http_status,retryable=False)。固定错误：VALIDATION_ERROR/422、NOT_FOUND/404、ACTIVE_RUN_EXISTS/409、VERSION_CONFLICT/409、STALE_APPROVAL/409、IDEMPOTENCY_CONFLICT/409、APPROVAL_REQUIRED/403、UNSUPPORTED_OPERATION/405、DEPENDENCY_UNAVAILABLE/503、LIMIT_EXCEEDED/429、OUTCOME_UNKNOWN/409。业务工具返回统一响应；SSE开始前用HTTP错误，开始后发error和正确终态事件。

每个owner资源查询把owner条件放进数据库查询本身，不能先取全量再在UI过滤。物料/库存为同组织共享目录；草稿、订单、运行、审批、偏好、产物按owner隔离，订单引起的共享库存写入必须带业务操作关联。

## 5. 每个任务怎么做

核心行为先写一个能暴露缺陷的测试，执行确认是预期失败，再实现并重跑。环境/依赖故障先修环境，不把ImportError任意当成业务红灯。不为只读文档、脚手架文本机械补测试；用构建、导入、实际命令验证。

每任务完成：检查私有实现未越过边界、相关检查通过、模块README更新。允许先做本地任务commit；阶段满足必要验收后才统一push并打阶段标签。每阶段只推进到交付，不自动继续下一阶段。

## 6. 交接文件

每阶段维护`evidence/Pxx.md`，至少写：实际环境、实现任务、命令及退出码、断言结果、fake/live、数据源、浏览器步骤/截图、产物、未运行项、已知问题。最后写下一Agent要读取的入口和未解决限制。

模块README包含职责、不负责的范围、公开方法/调用例子、依赖、错误/边界、测试命令、关键路径。README与真实代码同步，不粘贴一页空泛技术栈。

若中途交接，新增/更新`docs/delivery/HANDOFF.md`：当前阶段/任务、当前HEAD、working tree状态、已完成/未完成、最后失败命令、下一步。未验收的任务不勾选。恢复Agent先读该文件和实际代码，不重新搭脚手架。

## 7. 最终阶段收尾

执行当前阶段plan的检查和spec全部必需验收；跑受影响前置回归。更新spec勾选、evidence、STATUS与模块说明。按[Git规则](../delivery/GIT_WORKFLOW.md)显式暂存路径、commit、push、核对SHA、推tag并核对解引用commit。交付报告只包含实际结果和链接；失败时留在当前阶段并报告，不假称上传成功。

文档规划更新使用docs提交，不创建phase-pxx功能标签，不将P00标完成。

## 8. 可直接使用的证据和交接格式

下面是未来实施者填写格式，不能将示例状态改成passed后省略实际执行。

```markdown
# Pxx 实施证据
status: implemented / offline_verified / live_verified / browser_verified（只保留实际完成项）
stage: Pxx
environment: OS / Python / Node / lockfile版本 / Mongo模式
model_mode: fake 或 live
data_source: local_seed / local_snapshot / remote_erp（逐模块写）

## 实现范围
- 任务编号、公开接口、关键文件

## 实际执行
| 验收ID/测试名 | 命令或浏览器步骤 | 退出码/实际结果 | 证据路径 |
|---|---|---|---|

## 数值与业务事实
- 期望、实际、数据库/文件核对方法；不只粘模型回答

## 未运行与已知问题
- 哪项not_run、缺什么条件、影响哪个验收

## 下一阶段输入
- 模块README、接口、入口、配置与残留限制
```

```markdown
# HANDOFF
stage: Pxx
current_task: Pxx-Tyy
head: 实际SHA
working_tree: clean或逐项列未提交改动
previous_phase_tag: 名称与解引用SHA
completed: 已完成且有证据的任务
remaining: 未完成任务及顺序
last_command: 实际命令
last_exit_code: 实际值
last_error: 关键错误原文摘要，移除凭证
next_action: 接手者第一步可执行动作
do_not_repeat: 已完成安装/迁移/数据写入，及其核对依据
```

最终报告用普通中文说明实现、验证、限制、commit/tag和停止位置；不要只返回“全部完成”。规划者后续可基于commit和evidence进行审查，不能仅依赖实施Agent自己的结论。
