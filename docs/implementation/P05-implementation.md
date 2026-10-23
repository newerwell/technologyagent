# P05 Harness与评审 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans if available; otherwise follow the task checklist directly. Implement only this stage.

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

- [ ] 写正常planning→executing→reviewing→result、reviewing→executing修订、waiting_input保持未完成等断言；非法转换抛具名错误。
- [ ] phase在节点真实进入时更新，不靠文本包含“正在分析”推断；重复相同阶段不发重复事件。
- [ ] 初始旧状态缺新字段时用兼容默认值；确保P04保存的草稿和checkpoint继续恢复，不改变既有node name。
- [ ] 执行phase单测和P04 checkpoint回归，确认P05未破坏已完成MVP。

### P05-T02：结构化计划与证据驱动更新

**Files:** Extend `agent/harness.py`；Create `contracts/workflow.py`、`tests/unit/test_plan_updates.py`；Modify contracts/events导出。
**Interfaces:** PlanItem(id,title,status,evidence_refs,required_action)；`update_plan_from_result(plan,tool_result)->list[PlanItem]`。

- [ ] 定义查询/采购/分析的少量计划模板或结构化生成，校验id唯一、有限步骤；问候可无业务计划。
- [ ] 步骤只有关联成功tool result或已验证业务事实才done；失败failed、未执行pending，取消后剩余skipped。
- [ ] 测试模型请求直接把未执行“创建订单”标done时不能生效；工具失败不增加成功步骤。
- [ ] 发plan事件并持久化，同状态签名去重；运行plan测试与事件schema检查。

### P05-T03：确定性结果检查

**Files:** Create `agent/review.py`、`tests/unit/test_deterministic_review.py`。
**Interfaces:** `deterministic_review(state)->ReviewResult(passed,checks,needs_revision)`，checks有check_id/pass/reason/evidence_refs。

- [ ] 先写测试：工具总额66000分，候选结构化回答65000分，NUMERIC_MATCH失败；不存在SourceRef的结论SOURCE_EXISTS失败。
- [ ] 检查库存scope、数值/金额、草稿字段/版本、审批与订单真实结果；从持久状态和服务读取事实，不只检查“已经审批”字样。
- [ ] 未成功订单不能通过ORDER_EXISTS；现有完成订单只查结果，不再执行写工具。
- [ ] 执行deterministic_review测试，失败reason必须能指向具体字段和依据，方便修订而非泛称“不够准确”。

### P05-T04：语义评审与有限修订

**Files:** Create `agent/rubrics.yaml`；Extend review/harness；Test `tests/integration/test_review_loop.py`。
**Interfaces:** semantic_review使用ModelPort/RunBudget；revision只允许补查只读、补充产物或改输出；需要变更业务必须新草稿/新确认。

- [ ] 先固定deterministic结果，再让模型按任务rubric判断遗漏与可读性；最终passed=硬检查通过且语义检查通过，模型不能覆盖硬失败。
- [ ] 第一次评审不通过revision_count从0到1，第二次到2，第三次仍不通过则failed并解释未完成项。预算不足更早停止。
- [ ] 成功订单写入的operation_id保留在state，修订节点无权重放submit；新写建议进入独立批准流程。
- [ ] scripted grader测试一次修订成功/连续失败/预算耗尽/订单已成功四条路径；断言连续失败恰为3次检查。

### P05-T05：工作流面板

**Files:** Create `frontend/src/components/workflow/{HarnessPhaseBar,PlanPanel,ReviewPanel}.tsx`、`frontend/src/tests/workflow.test.tsx`。
**Interfaces:** 只消费phase/plan/review事件与RunView，不新增第二套推断状态。

- [ ] UI区分正在执行、等待确认、评审未通过、失败、成功；phase=result但run.failed仍显示失败。
- [ ] 展示check_id的用户可读说明与对应数据引用，不展示原始prompt或私有推理文本。
- [ ] 测试刷新恢复计划、失败步骤、修订次数、重复事件去重；waiting_input不触发自动发送新消息。
- [ ] Vitest/typecheck/build通过，浏览器完成一轮带修订的可读展示。

### P05-T06：综合验收与交付

**Files:** Create `tests/integration/test_harness.py`、`evidence/P05.md`；Extend stage manifest。
**Interfaces:** P05-A01..A06覆盖正常/错误数值/连续失败/写入保护/限额/刷新。

- [ ] 真实模型跑库存与订单后补充说明场景；运行scripted fault案例确保行为可复现。
- [ ] 对数据库核对订单数、操作记录、审批消费，不用UI没有重复卡片替代幂等验证。
- [ ] 更新Harness和review模块README，记录硬检查与语义评审的各自限制。
- [ ] 完成offline/live/browser证据，推送并核对`phase-p05`后停止。
