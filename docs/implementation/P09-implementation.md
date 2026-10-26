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

- [x] 汇总实际模型/工具调用、parent_call_id/actor、阶段/审批/产物、耗时、error和data_source；工具注册清单与调用次数分别统计。
- [x] usage缺失显示unknown；原始工具参数不返回。trace接口按owner隔离，无额外独立监控平台。
- [x] 同run summary与持久ToolCall记录核对；失败run返回失败调用及业务效果摘要。
- [x] trace与owner隔离测试通过，日志/响应不含secret哨兵。

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

- [ ] 离线独立库、浏览器、运行报告已建立；真实模型完整最终演示未通过，且未覆盖所有步骤于同一连续批次。
- [ ] F02/F03/F04/F08/F11/F12真实模型尝试均已留存；F02/F03/F04/F08/F11未通过要求的3/3。
- [ ] 已记录DB快照与部分业务事实；报告文件解析与浏览器结果分开，但最终全链路DB核对未完成。
- [x] 汇总F01..F18实际状态；F15/F16缺环境记为not_run。F02/F03/F04/F08/F11真实模型结果不满足门槛，总体验收保持未通过。

### P09-T04：桌面与手机操作验收

**Files:** Extend Playwright config与`tests/e2e/responsive.spec.ts`；保存必要脱敏截图于evidence/screenshots/。
**Interfaces:** 1440×900与390×844两个项目，同一核心动作和判断。

- [ ] 输入、工具卡、审批、历史等浏览器套件已运行；全部错误重试及每种报告下载操作的人工验收未完成。
- [x] 1440×900与390×844无主体水平溢出，手机订单输入可读可操作；Playwright断言通过。
- [ ] 已实际检查本轮桌面/手机截图；尚未逐个打开图表及四种报告核对所有格式和金额。
- [x] 保存浏览器报告和两张截图；完整browser入口exit0，15/15。

### P09-T05：全新环境、启停与备份恢复

**Files:** Create `scripts/{backup,restore}.ps1`、`docs/operations/{LOCAL_RUN,RECOVERY,BACKUP}.md`；Update start/stop、根README、.env.example。
**Interfaces:** 备份同时覆盖业务DB、checkpoints、展示消息、operations、Artifact元数据和实际文件；备份manifest记录hash/版本。

- [x] 本机备份脚本要求维护确认且应用进程停止，备份隔离测试库与storage并生成manifest/hash。
- [x] restore验证显式目标/测试库前缀、manifest与hash，恢复到新测试库和storage目录；DB计数与11个文件SHA一致。
- [ ] `uv sync`/`npm ci`在当前工作树通过；全新目录按锁文件启动未执行。
- [x] 保留本轮审查所需完整真实调用轨迹；未宣称新目录启动或生产恢复已验。

### P09-T06：最终证据与远程交付

**Files:** Create `evidence/P09.md`；Update STATUS、FINAL-ACCEPTANCE、所有实际改变的模块说明。
**Interfaces:** 本地完整版本与真实ERP结果独立声明；功能phase-p09标签不能包含尚未完成的必需检查。

- [ ] F01–F18均有状态和报告索引；P03/F04/F08/F11硬门槛失败，不能宣称完整验收。
- [x] 已知限制与本机运行说明已更新；README明确P09进行中，不称生产上线。
- [ ] 代码/证据提交与CI远程核对后可完成审查交付；必需live门槛未过，不创建`phase-p09`。
- [ ] 报告本轮通过、失败、not_run、commit与ERP边界后停止；不进入P10。
