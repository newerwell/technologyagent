# P05 Harness与评审 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans if available; otherwise follow the task checklist directly. Implement only this stage.

**当前复核：** 实现已推送，phase-p05→1ddfc7c不动；R01–R06待补修，A04未通过独立验收。原勾选记录历史实施进度；本轮执行入口为 [P05及前置补修计划](./P05-followup.md)，不开始P06。

**Goal:** 将真实任务转成可见计划、执行、检查和有界修订过程。
**Architecture:** graph状态控制阶段，确定性检查保业务事实，模型仅补语义完整性审查。
**Tech Stack:** 既有LangGraph/事件链；rubrics.yaml配置评审要求。
**Spec:** [P05](../specs/P05-harness-review.md)、共享契约预算与阶段事件。

## Global Constraints

最多2次修订/3次检查；模型/工具限额优先；phase与Run.status分离；已成功业务操作不能被评审触发重新提交；不能把私有模型思维作为UI内容。

## Review Focus

数值不符被模型评分覆盖→T03；反复修订不停→T04；评审重放订单→T04/T06；等待审批误完成→T01/T05；计划无证据标done→T02。

### P05-T01：状态与阶段转换

**Files:** Modify `agent/state.py`、`agent/graph.py`；Create `agent/harness.py`、`tests/unit/test_phase_transitions.py`。
**Interfaces:** AgentStateV1兼容增加task_type/plan/phase/review/revision_count/evidence_refs；`transition_phase(state,target)->StateUpdate`。

- [x] 写阶段、修订、waiting_input与非法转换断言。
- [x] phase在执行路径进入时更新；重复状态不重复发事件。
- [x] 初始旧状态使用兼容默认值；P04 checkpoint node name未改。
- [x] 执行phase单测和P04 checkpoint回归。

### P05-T02：结构化计划与证据驱动更新

**Files:** Extend `agent/harness.py`；Create `contracts/workflow.py`、`tests/unit/test_plan_updates.py`；Modify contracts/events导出。
**Interfaces:** PlanItem(id,title,status,evidence_refs,required_action)；`update_plan_from_result(plan,tool_result)->list[PlanItem]`。

- [x] 定义有限任务计划模板；普通问候允许没有业务步骤。
- [x] 仅成功工具事实及来源可将步骤标done；失败工具转failed。
- [x] 模型候选状态/来源会被清理，模板未开放模型写工具。
- [x] plan事件持久化并按签名去重；契约生成检查待最终复跑。

### P05-T03：确定性结果检查

**Files:** Create `agent/review.py`、`tests/unit/test_deterministic_review.py`。
**Interfaces:** `deterministic_review(state)->ReviewResult(passed,checks,needs_revision)`，checks有check_id/pass/reason/evidence_refs。

- [x] 数值、来源、范围等硬失败用例先写并验证。
- [x] 检查结构化业务事实、计划依据和订单真实持久状态。
- [x] 完成订单评审只读查询，不会重入submit节点。
- [x] 失败结果含具体check_id、原因和可用引用。

### P05-T04：语义评审与有限修订

**Files:** Create `agent/rubrics.yaml`；Extend review/harness；Test `tests/integration/test_review_loop.py`。
**Interfaces:** semantic_review使用ModelPort/RunBudget；revision只允许补查只读、补充产物或改输出；需要变更业务必须新草稿/新确认。

- [x] 硬检查通过后才调用rubric语义评审；语义结果不能改变硬检查。
- [x] 最多2次修订/3次检查；共享模型预算提前耗尽即停。
- [x] 订单图在检查数据库后结束，评审不重放业务副作用。
- [x] ScriptedModel覆盖一次修订、连续失败和预算耗尽；订单持久化回归由P04 checkpoint/幂等用例覆盖。

### P05-T05：工作流面板

**Files:** Create `frontend/src/components/workflow/{HarnessPhaseBar,PlanPanel,ReviewPanel}.tsx`、`frontend/src/tests/workflow.test.tsx`。
**Interfaces:** 只消费phase/plan/review事件与RunView，不新增第二套推断状态。

- [x] UI分开显示工作阶段、等待输入、评审未通过、失败与成功；Run.status优先。
- [x] 展示check_id、说明和来源，不向UI发送prompt或私有推理。
- [x] reducer与RunView快照恢复计划/评审/修订计数，事件按run+seq去重。
- [x] Vitest/typecheck已运行通过；浏览器检查及production build待stage manifest记录。

### P05-T06：综合验收与交付

**Files:** Create `tests/integration/test_harness.py`、`evidence/P05.md`；Extend stage manifest。
**Interfaces:** P05-A01..A06覆盖正常/错误数值/连续失败/写入保护/限额/刷新。

- [x] 真实模型跑库存与审批后订单说明场景；Scripted fault案例可重复验证有限修订和停止行为。
- [x] 对数据库核对订单数、operation、审批消费，不用UI没有重复卡片替代幂等验证。
- [x] 更新Harness、review、workflow/contracts模块README，记录硬检查与语义评审的各自限制。
- [x] 完成offline/live/browser证据；实现提交CI run 40091398833已通过，最终远程交付与`phase-p05`核对见本阶段交付记录。
