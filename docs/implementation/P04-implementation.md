# P04 订单与审批 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans if available; otherwise follow the task checklist directly. Implement only this stage.

**Goal:** 实现可编辑、需确认、可重启恢复且不重复下单的采购MVP。
**Architecture:** 草稿是服务器事实，Approval绑定版本与hash；checkpoint恢复流程，Mongo事务保证订单/库存/批准/幂等结果一致。
**Tech Stack:** 既有图与Mongo事务，锁定版本Mongo checkpointer。
**Spec:** [P04](../specs/P04-orders-approval.md)、[接口映射](./INTERFACES.md)第5节。

## Global Constraints

order_create只收draft_id/approval_id/idempotency_key；金额不取模型JSON；120秒认领租约/15秒事务；图恢复可重跑节点；采购新单只增inbound、不增on_hand；owner隔离。

## Review Focus

旧草稿批准→T01/T03；节点重跑和重复resume→T02/T03；事务中途崩溃→T03/T05；报价/库存版本竞争→T03；仅UI按钮去重→T04/T06。

### P04-T01：草稿准备、字段补充、版本更新

**Files:** `contracts/order_workflow.py`、`domain/{orders,inventory}.py`、`services/drafts.py`、`repositories/drafts.py`、`api/drafts.py`；Test `tests/integration/test_drafts.py`。
**Interfaces:** DraftService.prepare/patch按映射；OrderDraft额外保存snapshot_versions、报价ID、单位/币种和字段补充信息。

- [x] 写固定案例：P001/W01/Q01/55→66000分；patch quantity60→version+1/72000；缺warehouse只返回missing_fields，不猜默认仓库。
- [x] 根据有效报价服务端构建items，同supplier+warehouse分组；同part同quote可合并数量；跨供应商分不同草稿，每张单独确认。
- [x] patch用expected_version条件更新；旧pending approval在同事务标superseded，不能保留一个能批准旧金额的中断。
- [x] 跑draft测试，非法part/quote/金额/数量和被停用supplier拒绝；补领域README，解释审批与订单状态不同。

### P04-T02：持久中断与resume

**Files:** Create `agent/checkpoints.py`、`agent/order_nodes.py`、`services/approvals.py`；Modify graph、api/runs；Test `tests/integration/test_checkpoint_resume.py`。
**Interfaces:** 节点名固定`prepare_order_v1`、`supplement_order_v1`、`approve_order_v1`、`submit_order_v1`；resolve返回ResumeResolution，不提前消费批准。

- [x] 用假模型+真实Mongo checkpointer建立waiting_input，中断payload必须能JSON序列化；关闭/重开checkpointer后读取同thread/run状态。
- [x] 分开字段补充、草稿展示/确认和副作用节点；interrupt之前只能幂等准备，不创建订单；不能catch吞掉框架中断异常。
- [x] 字段不足时将partial DraftInput保存checkpoint；supplement的expected_version在尚无草稿时可空，但interrupt_id/run/owner必须校验。生成正式草稿后，approve/edit必须携带服务端version；不得给无效零件或缺字段草稿生成可执行批准。
- [x] resume验证owner/run/interrupt_id/version/决定后再调用同checkpoint；重复approve由原operation结果收敛，edit创建新草稿版本并展示新确认。
- [x] waiting_input持久后stream_end(reason=waiting_input)且不发completed；resume新流同run_id继续seq。Mongo saver关闭/重开由集成测试验证；FakeAgent 与真实模型 Chromium 流程均验证独立服务进程重启后刷新恢复。

### P04-T03：批准、幂等与本地提交事务

**Files:** Create `services/mutations.py`、`repositories/{operations,orders}.py`、`ports/orders.py`；Extend inventory repository/indexes、MCP orders；Test `tests/integration/test_order_idempotency.py`。
**Interfaces:** MutationService.execute；OrderWriter.create_from_draft；InventoryRepository.adjust_inbound；operation状态processing/succeeded/failed/outcome_unknown。

- [x] 并发与重复提交相同key收敛为一单；同key不同payload为409；已消费审批重传返回原结果；未批准直调API/MCP写工具拒绝且不创建operation。
- [x] 以owner/action/key唯一认领operation，持有lease与过期时间；先核对已有成功结果再执行业务写入，判定保留owner/hash验证。
- [x] 事务中重新读取草稿/审批、quote/supplier、库存版本；校验决定、hash、版本和时效；CAS调整inbound与version，写订单/批准消费/operation结果。事务无模型/远程HTTP。
- [x] 乐观版本更新确保库存读写冲突触发重新校验；事务重试回调无外部副作用。报价字段变化由快照hash锁定。
- [x] 创建55件后inbound=65、预计80、on_hand仍20；事务中断回滚、提交后丢响应读回及过期租约恢复均有Mongo集成断言。

### P04-T04：确认卡片与订单页面

**Files:** `frontend/src/components/approval/{ApprovalCard,SupplementForm}.tsx`、`frontend/src/app/orders/page.tsx`、`backend/app/api/drafts.py`（草稿/审批/订单路由）；Extend `frontend/src/hooks/useChat.ts`；Test `frontend/src/tests/approval.test.tsx`。
**Interfaces:** 使用run.pending_interrupt和ResumeRequest；展示的是服务端草稿version，不由前端重新计算总额。

- [x] 确认卡展示supplier/warehouse/items/单价/数量/总额/来源，提供approve/reject/edit；编辑回服务器获得新版本后才允许approve。
- [x] 字段补充显示missing_fields；失败显示错误并保留表单值，不提前显示创建成功。
- [x] 提交后锁定按钮；processing/outcome_unknown 显示对账状态，不生成假订单号。
- [x] 测试双击、旧version409、拒绝、重载待审批；订单列表从实际GET读取，Vitest/typecheck/build通过。

### P04-T05：崩溃恢复与对账

**Files:** `services/reconciliation.py`、`tests/integration/test_order_idempotency.py`、`test_checkpoint_resume.py`；Extend启动恢复、RunView。
**Interfaces:** reconcile(operation_id,ctx)；检查checkpoint状态与DB事实，不能仅看聊天文本判断成功。

- [x] 在认领后、事务写订单后未commit、commit成功但丢响应三个位置注入故障；注入钩子只在测试配置启用。
- [x] 已成功operation返回原订单；未提交事务自然回滚，租约失效后可重新认领；提交结果通过operation reconcile读回。
- [x] 事务断言在途量、审批、订单和operation保持一致；对账不能以聊天文本判断成功。
- [x] waiting_input从持久checkpoint保留；具备检查点的运行恢复同一run；无检查点仍按既有恢复规则失败。P02取消/锁回归在全量integration中执行。

### P04-T06：MVP浏览器与交付

**Files:** `tests/e2e/order-flow.spec.ts`、`tests/integration/test_approval.py`、`evidence/P04.md`；Update验证manifest。
**Interfaces:** P04-A01..A08逐条对应测试与人工步骤；真实模型负责理解需求，DB断言负责业务事实。

- [x] FakeAgent 全量 Chromium 与真实模型订单 Chromium 浏览器流（55→编辑60→停止并重启服务进程→刷新→批准→720元），与seed初始订单数比较只增加一单。
- [x] 独立重置隔离测试库核对55件标准案例、拒绝、缺字段、跨owner、报价过期/库存变化重新确认。
- [x] 故障注入测试通过；UI未出现假成功；evidence分别记录live/browser/事务测试。
- [x] 更新MVP状态与模块说明已完成；offline、live、FakeAgent browser、live browser 验收通过。阶段提交/推送/标签核验待执行。
