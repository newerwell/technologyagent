# P04-fix1 与 P03 残留补验收

日期：2026-10-24
基线：`origin/main=dd1a07266c000c01ce181d7d389c42f3582fbdca`；`phase-p04=97e1972fb21cd3ffa28570233853a0574807236e`（旧标签未移动）
数据库：只使用 `technologyagent_test_*` 隔离库；`technologyagent_dev` 未 reset 或用于验收写入。未读取、展示或提交密钥。

## 补修实现

- P04-F01/F02：Mongo 事务提交验证 operation 租约持有人/有效期；取消栅栏与提交事务竞争。等待态取消终结 run 并清 pending interrupt；已提交结果保留原订单事实。
- P04-F03/F04：resume 认领前校验并持久化决定键/hash；相同决定重放回原结果，不同 payload 冲突。启动恢复依据持久决定、Mongo checkpoint 与 operation 回读，覆盖认领后和订单提交后故障窗口。
- P04-F05/F06：草稿 DTO 标注所属 run/interrupt；订单页和聊天使用同一 resume 入口；多供应商草稿按版本逐张确认，拒绝和批准结果均进入终态摘要。
- P04-F07/F08：草稿准备/修改与提交事务重查零件有效性；模型意图抽取先认领幂等 run，计入持久模型次数、取消检查和活跃 deadline。
- P03-R02/R03/R07：数值 claim 按字段、单位、零件/仓库绑定；结论冲突按零件范围校验；正式正文校验通过前缓冲；`length`、`content_filter`、异常终止均不作为成功结束。对无关日期、编码、版本数字不再套用业务数字规则。

确定性回归在修复前先出现失败：旧租约持有人仍能返回成功、停用零件成功写入、waiting run 取消后仍可继续、非法编辑后 run 失败、成功决定重放返回 409；P03 日期/版本数字和“元”字段反例、跨零件库存结论范围反例也分别失败。修复后目标回归通过，完整结果见下文。

## Offline 与浏览器

- `uv run python -m scripts.verify_stage P04 --mode offline --report .runtime/reports/P04-fix1-offline.json`：通过，9/9 checks，65 unit、128 integration、frontend typecheck/test/build、contracts 均通过；总计 419.88 秒。
- `uv run python -m scripts.verify_stage P04 --mode browser --report .runtime/reports/P04-fix1-browser.json`：通过，8/8 Chromium E2E；包含等待任务恢复、取消、同视图旧刷新、订单页批准后返回原聊天、服务重启；总计 67.95 秒。
- 后端目标回归：模型意图单测及草稿/审批/幂等/checkpoint 用例在本地运行通过；前端 `useChat.test.tsx` 8/8。
- 首次 browser manifest 因未启动本地服务而失败；启动使用 `technologyagent_test_p04_browser` 后，订单 E2E 又发现全局审批卡选择器包含种子卡。选择器改为限定当前金额卡片，重跑完整 8/8 通过。失败报告保留在忽略的 `.runtime/reports/`。

## 真实验收

- P04 live：通过。隔离库基线订单数 2，I001 `on_hand=20/inbound=10`；模型补充 W01 后草稿 S01/Q01、55 件、66,000 分；同 run 恢复并批准后，订单数 2→3、I001 `inbound=65/on_hand=20`，订单 55 件/66,000 分，approval `consumed`、operation `succeeded`、run `completed`。本轮详细轨迹在忽略目录 `.runtime/live/p04-order-workflow-attempts.json`。
- P04 live browser：通过，`tests/e2e/order-flow.spec.ts` 1/1。真实模型产生草稿，UI 将数量 55 改为 60（总额 72,000 分），服务重启后从订单页批准并回到聊天核对完成态；独立 browser 库订单增加 1，I001 `inbound=70/on_hand=20`。该编辑路径与上面的 55 件事务验收分属两个隔离库。
- P03-A06：4批固定3×3共36次尝试，批次通过数为0/9、0/9、2/9、2/9；所有脱敏事件轨迹与每次理由保存在 `evidence/P03-A06-live-traces.json`。失败轨迹反映模型答案/工具选择不满足验收（数值或最终结论不匹配、缺少符合7天条件的预览、未明确证明 P003 无有效报价），P04 live 结果没有替代该验收。

## 交付门槛

首轮实现提交 `1f9ad90cb12bf821e0369012236ea8e00b733f61` 已推送至 `origin/main`，远端 SHA 核对一致；GitHub Actions CI [run 40083782561](https://github.com/newerwell/technologyagent/actions/runs/40083782561) 结果为 `success`。

P04-fix1 实现可供复核。由于 P03-A06 尚未通过，不创建 `phase-p04-fix1` 或 `phase-p03`，不宣称阶段完整通过，不开始 P05。
