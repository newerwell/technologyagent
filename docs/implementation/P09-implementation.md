# P09 综合交付 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans if available; otherwise follow the task checklist directly. Implement only this stage.

**Goal:** 得到可重现、可诊断、可备份的本地完整演示版及可信验收记录。
**Architecture:** 追踪与恢复围绕既有run/operation/checkpoint，不搭第二套任务系统；跨阶段整体验收从数据库事实判断。
**Tech Stack:** 既有工具链、Playwright、PowerShell运行交付。
**Spec:** [P09](../specs/P09-acceptance-operations.md)、[最终验收](../specs/FINAL-ACCEPTANCE.md)。

## Global Constraints

F01–F14/F17–F18本地必需；F15/F16真实ERP单独记录；真实模型代表场景各至少3次、保留全部尝试；本地演示不等于生产上线。

## Review Focus

trace只能列配置不能说明执行→T01；取消/未知写状态错误重试→T02；只保留成功样例→T03；窄屏无法批准→T04；备份未含文件/恢复错库→T05。

### P09-T01：关联追踪与诊断

**Files:** Create `services/tracing.py`、`api/diagnostics.py`、`tests/integration/test_trace_summary.py`；Extend事件/tool记录。
**Interfaces:** `TraceService.summary(run_id,ctx)->RunTraceSummary`；GET /api/runs/{id}/trace按owner授权，返回脱敏摘要。

- [ ] 汇总实际模型/工具调用、parent_call_id/actor、阶段/审批/产物、耗时、error和data_source；工具注册清单与调用次数分别统计。
- [ ] usage缺失显示unknown而非0；参数日志脱敏且不保存Key、cookie或MCP bearer。诊断UI可用简单详情面板，不扩建独立监控平台。
- [ ] 对同一run核对summary计数与原始ToolCall记录；失败run能查到具体失败调用及是否有业务效果。
- [ ] 运行trace测试和owner隔离测试，确认日志输出不包含测试植入的secret哨兵字符串。

### P09-T02：孤儿运行与故障恢复

**Files:** Create `services/recovery.py`、`tests/integration/test_recovery_matrix.py`；Modify bootstrap/health/运行终态。
**Interfaces:** recover_orphan_runs(now)按状态、checkpoint、operation事实分类；不能按“运行很久”直接重新下单。

- [ ] waiting_input保留原中断；无副作用的可恢复节点从checkpoint继续；成功operation返原结果；processing等租约/查事务事实；outcome_unknown先外部核对。
- [ ] cancel只阻止新调度；已有commit不回滚，正在未知提交显示核对状态，结果确认后再给最终可用操作。
- [ ] DB无法持久化时不发新业务写；MCP故障禁依赖工具、Docker故障只影响产物/执行；不偷偷换数据源或宿主shell。
- [ ] 故障矩阵覆盖模型/MCP/DB/Docker/进程重启/浏览器断线；断言无重复订单、无永远占住thread锁、无假成功。

### P09-T03：可重复的最终场景集

**Files:** Create `tests/e2e/full-procurement.spec.ts`、`tests/live/test_final_scenarios.py`、`scripts/run_acceptance.py`；Update FINAL-ACCEPTANCE。
**Interfaces:** `run_acceptance --scope local|erp --mode offline|live|browser --report ...`调用已有阶段检查，不另造测试语义。

- [ ] 用独立测试库从fixtures/v1开始，按最终演示顺序完成查询→推荐→报告→草稿→编辑60→重启批准→收货→偏好→trace。
- [ ] F02/F03/F04/F08/F11/F12每类真实模型至少3次，记录所有attempt、模型参数、来源、结果、耗时、调用轨迹与失败；硬错误必须修复后对应用例重跑。
- [ ] 核对数值/订单/流水来自DB；报告文件解析和浏览器结果分开记录。E2E使用seed固定时钟，真实远程使用当前时间并说明差异。
- [ ] 汇总F01..F18实际状态；F15/F16缺环境not_run，不能勾成passed，也不能阻止明确范围的本地版本交付。

### P09-T04：桌面与手机操作验收

**Files:** Extend Playwright config与`tests/e2e/responsive.spec.ts`；保存必要脱敏截图于evidence/screenshots/。
**Interfaces:** 1440×900与390×844两个项目，同一核心动作和判断。

- [ ] 验证输入、工具卡、长表格、审批编辑、错误重试、历史、下载均可操作；等待/失败不会被遮罩永久挡住。
- [ ] 断言document主体无横向溢出；表格可内部横向滚动，审批金额/确认按钮始终可读可点。
- [ ] 实际打开图表/报告核对中文、单位、截断和文件内容；不能仅用元素存在断言代替视觉判断。
- [ ] 保存尺寸、浏览器、步骤和截图，执行browser阶段命令，必要调整后只重跑受影响场景。

### P09-T05：全新环境、启停与备份恢复

**Files:** Create `scripts/{backup,restore}.ps1`、`docs/operations/{LOCAL_RUN,RECOVERY,BACKUP}.md`；Update start/stop、根README、.env.example。
**Interfaces:** 备份同时覆盖业务DB、checkpoints、展示消息、operations、Artifact元数据和实际文件；备份manifest记录hash/版本。

- [ ] 本机版本采用维护窗口：停止应用/MCP业务进程并确认无在途写，再备份DB和storage；不能在线分时复制两者却宣称一致快照。
- [ ] restore先验证显式目标路径/测试库前缀、备份manifest和hash，默认不覆盖开发库；恢复到独立测试环境核对订单/审批/checkpoint/文件关联。
- [ ] 从新目录按锁文件安装启动，不依赖原机器绝对路径、手工pip安装或隐含端口进程；验证start/stop只管理本项目。
- [ ] 清理本次无用临时容器/文件，保留应交付证据与示例；没有实测恢复成功不能写“备份可恢复”。

### P09-T06：最终证据与远程交付

**Files:** Create `evidence/P09.md`；Update STATUS、FINAL-ACCEPTANCE、所有实际改变的模块说明。
**Interfaces:** 本地完整版本与真实ERP结果独立声明；功能phase-p09标签不能包含尚未完成的必需检查。

- [ ] 对F01–F14/F17–F18逐项提供测试名/命令/退出码/截图或产物；核对全部必需live/browser实际执行。
- [ ] 写已知限制与启动/演示提示词；确认根README准确描述实现状态，删除过期“P00未开始”文案，但不抹掉历史证据。
- [ ] 做最终diff/锁文件/schema/相关检查；按规则commit、push、核对main、push annotated phase-p09、核对解引用SHA。
- [ ] 报告源码、运行方法、演示顺序、检查证据、commit/tag、ERP未验证项；停止，后续功能作为新需求按扩展指南规划。
