# P04：订单草稿、人工确认与持久恢复

状态：T01–T06实现已推送，phase-p04=97e1972已核对。本轮基础回归通过，但 [独立审查](../reviews/2026-10-24-P04-review.md) 有9项问题，先执行 [补修计划](../implementation/P04-followup.md)。P03三项残留及固定只读3×3尚未验收，P04历史订单live不能替代。目标仍是建议→草稿→确认→订单，并支持刷新/服务重启恢复。

## 任务

- [x] **P04-T01 草稿服务。** `services/drafts.py` 实现创建、字段补充和版本更新；`domain/orders.py` 校验有效零件、供应商、仓库、报价、正数量、整数分及服务端总额；同供应商和仓库归组；缺失项通过结构化 interrupt 请求，不猜测。
- [x] **P04-T02 接入持久检查点。** `agent/checkpoints.py` 配置 MongoDB checkpointer；`agent/order_nodes.py` 将字段补充、草稿展示、审批、提交拆成明确节点；resume 使用同 thread/run，先校验 interrupt_id/owner/version 再恢复。
- [x] **P04-T03 统一 MutationService。** `services/mutations.py`、`repositories/operations.py` 完成审批绑定、唯一索引、认领租约和reconcile；在事务内写订单、增加库存inbound/版本、消费审批并记操作结果，任一失败全部回滚；订单创建工具只调用该服务；MCP直调未批准也拒绝。
- [x] **P04-T04 审批卡片。** `components/approval/ApprovalCard.tsx`、`SupplementForm.tsx` 展示供应商、仓库、明细、单价、数量、总额、来源和版本；支持 approve/reject/edit；编辑后重新展示并再次确认，按钮提交后锁定防抖不能代替后端幂等。
- [x] **P04-T05 订单查询与异常恢复。** 实现订单列表/详情及运行待审批恢复；批准前重查报价与库存版本；过期/变更使审批 superseded；服务崩溃后能核对 processing 操作并返回已存在订单。
- [x] **P04-T06 核心测试与浏览器验证。** `tests/integration/test_approval.py`、`test_order_idempotency.py`、`tests/e2e/order-flow.spec.ts` 覆盖接受、拒绝、编辑、双击、并发、跨用户、服务重启和崩溃点；offline/FakeAgent全量浏览器与真实模型订单live/browser验收均有 evidence。

## 验收

| ID | 操作 | 通过条件 |
|---|---|---|
| P04-A01 | “刹车片补到目标库存，7天内到货，生成订单” | 展示S01/W01/55件/660.00元；未批准前新增订单数0 |
| P04-A02 | 缺仓库时补充W01；把数量改60 | 只询问缺失项；新版本展示720.00元，原审批失效 |
| P04-A03 | 拒绝审批 | 无新增订单；run有明确结束说明；草稿保留rejected |
| P04-A04 | 批准P001/W01的55件草稿，重复和并发提交相同请求 | 相对初始订单数只增1、同一订单ID；inbound从10变65、预计库存80，不再建议重复补货；同key不同payload返回409 |
| P04-A05 | 等待审批时重启后端再刷新并批准 | 恢复同一草稿和版本；最终只创建一次 |
| P04-A06 | 在认领后、事务内写订单后、事务提交后丢响应时注入崩溃 | 未提交全部回滚，已提交可核对原订单；审批/订单/inbound一致；租约到期可恢复，无重复单或永远processing |
| P04-A07 | 改报价/库存版本后批准；直调未批准MCP写工具 | 前者要求新确认；后者拒绝且DB无变化 |
| P04-A08 | 用户B恢复A的审批或修改A的草稿 | 返回404，不产生写入 |

## 本阶段结束后

核心MVP已有实现；原任务勾选保留交付历史。本轮审查发现取消/恢复/事务等缺口，修复并满足全部验收后才能标MVP完整通过，不能只以既有happy path或phase-p04标签判定。

## 阶段 Git 交付

- [x] 实现和本阶段验收完成；新增/变更模块包含中文README，说明职责、接口、运行例子与限制。
- [x] 更新本阶段evidence、任务勾选、架构图和扩展契约；检查改动及敏感文件，仅暂存本阶段明确路径。
- [x] 历史实现与phase-p04已推送并核对97e1972；标签保持不动。本轮未通过独立复核，后续补修使用phase-p04-fix1，仍须完整验收及远程核对。
- [ ] 向用户报告结果、实际检查、commit链接及阶段标签。推送未成功则标记“远程未交付”，不宣布阶段完成。
