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

**Files:** Create `contracts/approval.py`、`domain/{orders,inventory}.py`、`services/drafts.py`、`repositories/drafts.py`、`api/drafts.py`；Test `tests/integration/test_drafts.py`。
**Interfaces:** DraftService.prepare/patch按映射；OrderDraft额外保存snapshot_versions、报价ID、单位/币种和字段补充信息。

- [ ] 写固定案例：P001/W01/Q01/55→66000分；patch quantity60→version+1/72000；缺warehouse只返回missing_fields，不猜默认仓库。
- [ ] 根据有效报价服务端构建items，同supplier+warehouse分组；同part同quote可合并数量；跨供应商分不同草稿，每张单独确认。
- [ ] patch用expected_version条件更新；旧pending approval在同事务标superseded，不能保留一个能批准旧金额的中断。
- [ ] 跑draft测试，非法part/quote/金额/数量和被停用supplier拒绝；补领域README，解释审批与订单状态不同。

### P04-T02：持久中断与resume

**Files:** Create `agent/checkpoints.py`、`agent/order_nodes.py`、`services/approvals.py`；Modify graph、api/runs；Test `tests/integration/test_checkpoint_resume.py`。
**Interfaces:** 节点名固定`prepare_order_v1`、`supplement_order_v1`、`approve_order_v1`、`submit_order_v1`；resolve返回ResumeResolution，不提前消费批准。

- [ ] 用假模型+真实Mongo checkpointer建立waiting_input，中断payload必须能JSON序列化；关闭/重建图实例后读取同thread/run状态。
- [ ] 分开字段补充、草稿展示/确认和副作用节点；interrupt之前只能幂等准备，不创建订单；不能catch吞掉框架中断异常。
- [ ] 字段不足时将partial DraftInput保存checkpoint；supplement的expected_version在尚无草稿时可空，但interrupt_id/run/owner必须校验。生成正式草稿后，approve/edit必须携带服务端version；不得给无效零件或缺字段草稿生成可执行批准。
- [ ] resume验证owner/run/interrupt_id/version/决定后再调用同checkpoint；重复approve由原operation结果收敛，edit创建新草稿版本并展示新确认。
- [ ] waiting_input持久后stream_end(reason=waiting_input)且不发completed；resume新流同run_id继续seq。跑checkpoint测试确认重启仍恢复原草稿。

### P04-T03：批准、幂等与本地提交事务

**Files:** Create `services/mutations.py`、`repositories/{operations,orders}.py`、`ports/orders.py`；Extend inventory repository/indexes、MCP orders；Test `tests/integration/test_order_idempotency.py`。
**Interfaces:** MutationService.execute；OrderWriter.create_from_draft；InventoryRepository.adjust_inbound；operation状态processing/succeeded/failed/outcome_unknown。

- [ ] 先写并发approve测试：相同key产生一单，原id返回；同key不同payload409；已消费审批合法重传仍能返回原结果；未批准直调工具403。
- [ ] 以owner/action/key唯一认领operation，持有lease_owner和expires_at；核对已有成功结果在前、重新业务写入在后，所有判定保留owner/hash验证。
- [ ] 事务中重新读取草稿/审批、quote/supplier、库存版本；校验决定、hash、版本和时效；CAS调整inbound与version，写订单/批准消费/operation结果。不得在事务里调模型/远程HTTP。
- [ ] 用乐观版本更新确保库存读写冲突触发重新校验；事务重试回调不得含外部副作用。有效报价字段变化需版本或hash锁定，不能只比较ID。
- [ ] 断言创建55件后inbound=65、预计80、不再预警，on_hand仍20。所有事务错误全部回滚；运行事务与并发测试。

### P04-T04：确认卡片与订单页面

**Files:** Create `components/approval/{ApprovalCard,SupplementForm}.tsx`、`app/orders/page.tsx`、`api/orders.py`；Extend useChat；Test `frontend/src/tests/approval.test.tsx`。
**Interfaces:** 使用run.pending_interrupt和ResumeRequest；展示的是服务端草稿version，不由前端重新计算总额。

- [ ] 确认卡展示supplier/warehouse/items/单价/数量/总额/来源，决定按钮approve/reject/edit；编辑回服务器获取新版本后再允许approve。
- [ ] 字段补充只展示missing_fields；API失败保留用户输入并显示错误，不能按钮一按就显示“创建成功”。
- [ ] 提交后按钮暂时禁用；根据OperationResult为processing/outcome_unknown展示正在核对，不生成假订单号。
- [ ] 测试双击、旧version409、拒绝、重载待审批；订单详情从实际GET读取，Vitest/typecheck/build通过。

### P04-T05：崩溃恢复与对账

**Files:** Create `services/reconciliation.py`、`tests/integration/test_order_recovery.py`；Extend启动恢复、RunView。
**Interfaces:** reconcile(operation_id,ctx)；检查checkpoint状态与DB事实，不能仅看聊天文本判断成功。

- [ ] 在认领后、事务写订单后未commit、commit成功但丢响应三个位置注入故障；注入钩子只在测试配置启用。
- [ ] 已成功operation返回原订单；未提交事务自然回滚，租约失效后可重新认领；未知commit先查询实际operation/draft唯一单据，未确认前不再写。
- [ ] 在途量、审批消费、订单、operation必须一致；部分状态不一致视为数据错误并停止自动重试，不靠补一个“成功”消息修复。
- [ ] P02孤儿run恢复升级：waiting_input从checkpoint保留；具备检查点的运行按节点恢复；无检查点仍明确失败。跑恢复测试和P02取消/锁回归。

### P04-T06：MVP浏览器与交付

**Files:** Create `tests/e2e/order-flow.spec.ts`、`tests/integration/test_approval.py`、`evidence/P04.md`；Update验证manifest。
**Interfaces:** P04-A01..A08逐条对应测试与人工步骤；真实模型负责理解需求，DB断言负责业务事实。

- [ ] 浏览器用真模型完成生成55件草稿→编辑60→重启刷新→批准→查询720元订单；与seed初始订单数比较，只增加一单。
- [ ] 独立重置测试库核对55件标准案例、拒绝、缺字段、跨owner、报价过期/库存变化重新确认。
- [ ] 所有故障注入测试通过，UI未出现假成功；evidence区分live/browser/事务测试。
- [ ] 更新MVP状态与模块说明，提交/推送/核对`phase-p04`，停止。此时才可对用户声明采购MVP验收通过。
