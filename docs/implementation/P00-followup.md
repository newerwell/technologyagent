# P00 补修 Implementation Plan

> **For agentic workers:** 用户指定的其他Agent实施，规划者只审查/规划。若有executing-plans技能可按其执行；没有时直接按清单实施。只修本文件，不开始P01。

**Goal:** 修复P00真实启动链的来源与配置问题，为P01提供可靠底座。
**Architecture:** 保持既有应用结构，收紧本机入口，保证构建匹配当前配置，补实际代理链验证。
**Tech Stack:** 既有锁定版本，不升级框架。
**Spec:** [审查报告](../reviews/2026-10-23-P00-review.md)、P00原spec/plan及共享契约。

## Global Constraints

只修P00；不移动原phase-p00；不清理.dsh-meow或无关改动；临时服务只绑定回环并最终回收；不向开发库写假测试会话。

## Review Focus

TestClient未覆盖代理中间件→F01；旧构建使用旧API_PORT→F02；首页200误判成功→F02；移动已有阶段标签→F03；只写复测文档便说修复完成→F03。

### P00-F01：本机监听与可信来源

**Files:** Modify start.ps1、frontend/scripts/run-next.mjs、backend/app/api/session.py及必要配置；Test tests/integration/test_local_startup_boundary.py、test_session.py。
**Interfaces:** 保留原会话/API形状，身份仍由服务端固定生成，不增加公网认证工程。

- [ ] 先写回归：前端/后端仅127.0.0.1监听，非回环伪造XFF不获身份，正常同源会话可建立并读取。
- [ ] start.ps1和npm dev/start均显式hostname=127.0.0.1；后端显式关闭proxy headers，不以客户端XFF授予本机身份。记录该本机代理策略，不能一处关闭另一处仍依赖它授权。
- [ ] local session校验本机Host和允许Origin：跨源浏览器Origin拒绝、非本机Host拒绝，正常前端Origin与无Origin本机脚本按明确规则允许。允许端口从配置取；考虑Next代理会改Host，不能只按后端端口比较而误拒前端。
- [ ] 按实施手册统一Cookie为SameSite=Strict并同步测试/README；若确有必须Lax的功能需求，记录具体原因及对应校验，不无理由保留差异。
- [ ] 用隔离测试库/临时端口验证实际Next→Uvicorn链路：监听地址、转发头、Host/Origin、正常会话；TestClient只作补充。保存HTTP结果并finally回收本次服务。

### P00-F02：当前配置、源码与生产构建一致

**Files:** Modify start.ps1及必要启动配置；Test tests/integration/test_startup_configuration.py，可配PowerShell探针；Update scripts/frontend README。
**Interfaces:** 端口仍可配置；同配置的已运行进程保持重复start幂等。更改配置需明确停旧再启。

- [ ] 先API_PORT=A构建/启动，停止后以B重启；验证同源/health、/ready访问B而非A。临时端口由测试保留，避免占用用户服务。
- [ ] 最小实现每次实际新启动前端前按当前配置build，不再仅因BUILD_ID存在复用旧构建；保留已运行进程的幂等路径。
- [ ] 启动成功条件加前端同源/health和/ready；后端/DB不可用准确失败或降级，不能只因首页200报正常。build失败回收本次新增进程。
- [ ] 增加源码变化后的重新启动验证，不能继续展示旧页面；测试构建标记不提交到产品源码。
- [ ] 重跑P00 offline和必要浏览器回归，保存换端口前后结果，恢复原配置并清理临时进程/标记。

### P00-F03：文档、证据与修复交付

**Files:** Update evidence/P00.md或新增evidence/P00-fix1.md、docs/delivery/STATUS.md、相关模块README；修正过期状态与探针文案。
**Interfaces:** 旧验收保留，补修单独追踪R01/R02和F01/F02实际结果。

- [ ] 统一实际Cookie策略；checkpointer探针只写同实例保存/读取/继续，不声称已验证进程重启恢复。
- [ ] 报告原检查及新增链路测试的实际数量、命令、退出码和浏览器结果；not_run如实保留。STATUS只有修复验证后才能改为允许进入P01。
- [ ] 显式暂存本次代码/测试/说明/证据，commit并push origin/main；新建annotated phase-p00-fix1并推送、核对解引用SHA。原phase-p00继续指419ab23，不重写旧标签。
- [ ] 报告修复commit/tag和两项复现修复后的结果，停止。P01前置同时核对原基线及修复已包含于main，不将P01业务混入补修。

## 可复制给实施 Agent

```text
请只修复TechnologyAgent的P00审查问题，不开始P01。先读AGENTS.md、docs/reviews/2026-10-23-P00-review.md和docs/implementation/P00-followup.md。
按P00-F01/F02/F03实施：所有前端入口仅监听127.0.0.1；明确代理头与Origin/Host策略，补真实Next→Uvicorn链路；修复API_PORT改变但旧构建仍请求旧端口，并把同源/health、/ready纳入启动验证。
补测试并真实运行，更新P00 evidence/STATUS和模块README。保留已有phase-p00；完成后commit/push并创建phase-p00-fix1，核对远程SHA再报告。不要移动旧标签、删除.dsh-meow或修改无关代码。
报告结果与证据后停止，等待复核再做P01。
```
