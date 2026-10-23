# P00 工程底座 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans if available; otherwise follow the task checklist directly. User-selected external Agent implements this stage. Do not dispatch implementation from the planning chat.

**Goal:** 独立创建可运行前后端、事务数据库及后续阶段共用的验证入口。
**Architecture:** FastAPI只组装API；bootstrap管理生命周期；数据库/模型配置独立，前端同源代理。
**Tech Stack:** Python/uv、FastAPI/Pydantic/PyMongo、Next.js/React/TypeScript、MongoDB replica set。
**Spec:** [P00](../specs/P00-foundation.md)；先读[统一约定](./IMPLEMENTER-HANDBOOK.md)与[接口](./INTERFACES.md)。

## Global Constraints

从零编写；只做P00；端口3030/8030/9030/27027可配置；不提交Key；不提前创建P01–P09空实现。APP_MODE=local且仅本机建立开发会话。P00不启用真实模型、不要求沙箱。

## Review Focus

外部工作目录启动→T05；Mongo事务不可用→T03；配置缺失/Key泄露→T04；依赖API变化→T02；CI无测试被误当通过→T05。

### P00-T01：创建应用和请求边界

**Files:** Create `pyproject.toml`、`backend/__init__.py`、`backend/app/{__init__,main,config,bootstrap}.py`、`backend/app/api/{__init__,health,dependencies}.py`、`backend/app/contracts/common.py`；Create `frontend/package.json`、Next配置、app/layout.tsx、page.tsx、globals.css、lib/api.ts；Test `tests/integration/test_health.py`。
**Interfaces:** 产出`create_app(settings:Settings)->FastAPI`、`load_settings(environ)->Settings`、统一Envelope/AppError；后续由bootstrap注入Container。

- [x] 写health测试：GET /health为200，JSON不含环境变量和Key；未知路由404。先建立最小依赖环境并记录失败原因。
- [x] 创建最小可安装Python包、前端工程与代理，所有API地址由配置读取；/health只反映进程存活，/ready暂报告DB未配置503。
- [x] 执行`uv run pytest tests/integration/test_health.py -q`，期望全部通过；`npm --prefix frontend run typecheck`和build退出0。
- [x] 浏览器打开3030，页面能显示后端存活/就绪状态与错误文字；补`backend/README.md`、`frontend/README.md`，不提前堆聊天组件。

### P00-T02：锁定依赖与实际兼容探针

**Files:** Modify pyproject、uv.lock、frontend/package-lock.json；Create `scripts/__init__.py`、`scripts/check_compatibility.py`、`tests/integration/test_compatibility.py`。
**Interfaces:** `check_compatibility()->CompatibilityReport`；CLI退出0代表全部必需探针通过，不只是import成功。

- [x] 建立探针列表：FastAPI测试请求；LangGraph最小图invoke；无联网的假模型tool call循环；FastMCP临时服务/list_tools/call_tool；Mongo checkpointer保存再读取一次中断；DeepAgents假模型最小图组装。
- [x] 根据实际Python/Node运行选择兼容版本，写入锁文件。需要探针临时服务时只绑定回环、用随机端口、finally回收；不得接外部ERP或真实模型。
- [x] 执行`uv run python -m scripts.check_compatibility`。若DB探针尚待T03，可先明确not_run，T03后重跑；最终不能带必需skip交付P00。
- [x] 用`uv sync --frozen --group dev`和`npm --prefix frontend ci`验证锁文件可复现，报告实际版本、接口调用和退出码，不写未经验证的版本承诺。

### P00-T03：Mongo replica set、连接与事务探针

**Files:** Create `compose.yaml`、`scripts/init_db.py`、`backend/app/repositories/{mongo,indexes}.py`、`tests/integration/test_mongo_transactions.py`；Modify bootstrap、health。
**Interfaces:** MongoResources.open/close/transaction；ready依赖状态；初始化幂等。

- [x] 写两个真实DB测试：一次事务写A/B后抛异常，A/B均无新记录；正常事务后两者均存在。库名必须technologyagent_test_开头。
- [x] 按手册配置同一内外27027端口、ta-rs、健康检查和持久卷；init_db等待primary并幂等初始化索引。Mongo启动不能需要手工打开shell执行一次隐藏命令。
- [x] bootstrap在应用lifespan连接并退出时关闭；服务获取同一事件循环的AsyncMongoClient。ready检查ping/primary/事务能力，DB断开503。
- [x] 执行`uv run pytest tests/integration/test_mongo_transactions.py -q`并重跑T02探针；结果必须包含真事务回滚，不用mock代替。

### P00-T04：配置与本地会话

**Files:** Create `.env.example`、`backend/app/api/session.py`、`backend/app/services/sessions.py`、`tests/integration/test_session.py`；Modify config、dependencies、前端api。
**Interfaces:** `SessionService.create_local()->Session`、`resolve(cookie)->RequestContext`；用户身份只由服务端确定。

- [x] 写测试：请求体自填owner_id不生效；非local模式不能创建开发会话；无/无效cookie访问受保护接口401。测试身份B只通过测试dependency override注入。
- [x] local会话生成随机opaque token，DB保存摘要与24小时过期时间；设置HttpOnly、SameSite cookie；只开放回环开发环境和同源前端，不信任伪造forwarded header。
- [x] Key为空时model=disabled；敏感Settings repr/log脱敏。前端请求统一credentials，不拼user_id。
- [x] 执行`uv run pytest tests/integration/test_session.py -q`；检查.env.example无实际凭证，保护接口的错误Envelope与共享契约一致。

### P00-T05：启停、CI与阶段验证命令

**Files:** Create `start.ps1`、`stop.ps1`、`scripts/verify_stage.py`、`.github/workflows/ci.yml`、`tests/integration/test_stage_manifest.py`；配置Vitest/Playwright命令；Create `evidence/P00.md`。
**Interfaces:** 手册规定的verify_stage CLI；`.runtime/processes.json`记录本项目PID、启动时间、命令、端口，不入Git。

- [x] start从$PSScriptRoot定位，检查运行时与端口，不结束未知占用进程；只启动当前阶段已实现服务；Windows后台进程隐藏窗口，输出写.runtime。stop校验PID/启动时间/命令后仅关本项目。
- [x] 验证manifest严格映射阶段到真实命令；命令缺失、非0、pytest无测试均不能伪通过。CI使用同一manifest，数据库服务就绪后执行。
- [x] 从项目目录、另一个目录各启动并查询/停止；检查重复启动不重复开进程，关闭DB的ready503；清理探针临时文件。
- [x] 执行`uv run python -m scripts.verify_stage P00 --mode offline --report .runtime/reports/P00-offline.json`，再完成spec P00-A01..A05并记证据；按Git规则提交/推送/核对`phase-p00`后停止。

## 阶段输出

可启动空壳、已验证依赖、事务DB、本地身份、可复用验证命令。不得在README宣称AI对话可用。交付commit含源码/锁文件/测试/模块说明/evidence；不能只上传脚手架截图。