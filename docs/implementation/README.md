# 交给其他 Agent 的实施入口

当前执行入口（2026-11-10）：[P09完成度复审与剩余实施计划](./P09-remaining-2026-11-10.md)，按 N00–N09 顺序。P09尚未完成，不创建phase-p09、不开始P10。旧L00–L09手册和下表保留为设计与历史依据，不再从已经交付的L01重新实施。

复核基线de2af1b与远端一致，Clock及L01–L06主体已推送；当前精确SHA CI两job成功，本轮定向73 passed。最新固定live为8/13（P03内部2/9、F04为2/3、F11为0/3），仍有已实际复现的评审/oracle边界；完整恢复、用户环境和标签待交付。新手册区分已完成项与剩余项，列出A01–A07反例及逐卡实现和验收要求。

## 使用顺序

1. 实施Agent读取仓库AGENTS.md、[整体布局](../architecture/PROJECT_LAYOUT.md)、[共享契约](../specs/CONTRACTS.md)。
2. 读取[实施统一约定](./IMPLEMENTER-HANDBOOK.md)和[接口映射](./INTERFACES.md)。这里固定了跨任务名字、类型、命令、运行方式。
3. 只执行下表当前阶段；按任务编号顺序实现，先检查前置阶段的实际代码和远程标签。
4. 更新模块说明、测试和evidence，通过阶段验收后提交、推送、核对远程、打阶段标签，随后停止。
5. 下一Agent从远程最新代码、STATUS与证据接续，不仅凭聊天中“已完成”的说法继续。

| 阶段计划 | 实现重点 | 输入规格 |
|---|---|---|
| [P00 实施计划](./P00-implementation.md) | 环境、配置、事务数据库、健康、启停、验证入口 | [P00 Spec](../specs/P00-foundation.md) |
| [P01 实施计划](./P01-implementation.md) | 数据模型、合成数据、补货算法、业务API/页面 | [P01 Spec](../specs/P01-domain-data.md) |
| [P02 实施计划](./P02-implementation.md) | 原子run、事件持久化、SSE、历史/取消 | [P02 Spec](../specs/P02-chat-streaming.md) |
| [P03 实施计划](./P03-implementation.md) | MCP、真实工具循环、可信上下文和来源 | [P03 Spec](../specs/P03-agent-tools.md) |
| [P04 实施计划](./P04-implementation.md) | 草稿、持久中断、审批事务、幂等和恢复 | [P04 Spec](../specs/P04-orders-approval.md) |
| [P05 实施计划](./P05-implementation.md) | 计划和阶段、确定性/语义评审、修订预算 | [P05 Spec](../specs/P05-harness-review.md) |
| [P06 实施计划](./P06-implementation.md) | 容器执行、文件授权、图表报告和预览 | [P06 Spec](../specs/P06-artifacts-sandbox.md) |
| [P07 实施计划](./P07-implementation.md) | 版本路由、专家、技能和跨会话偏好 | [P07 Spec](../specs/P07-specialists-skills-memory.md) |
| [P08 实施计划](./P08-implementation.md) | 全量业务操作、收货事务、ERP映射/对账 | [P08 Spec](../specs/P08-erp-integration.md) |
| [P09 实施计划](./P09-implementation.md) | 故障恢复、全链路验证、运行交付 | [P09 Spec](../specs/P09-acceptance-operations.md) |

## 发给实施 Agent

当前 N00–N06 已关闭（离线/集成与证据归属）；下一步 N07 新候选全量门禁（offline/精确SHA CI/双尺寸browser/固定13外层live），随后 N08 全新检出完整恢复、N09 用户环境与Git收尾。交接指令见 [第14节](./P09-remaining-2026-11-10.md#14-直接交给其他agent的提示词)；不把旧批次、旧L卡或旧工作区状态当作当前事实。

新手册明确区分已有实现、工作区实现和计划新增文件；不要覆盖已有代码重新创建。文档中的assert是验收要求，不表示测试已执行。库的内部调用以锁文件及实际代码为准；应用端口、数据字段、错误语义和阶段范围按当前契约与计划固定。

规格决定做什么，实施计划决定怎么拆和怎么验证。若出现冲突，先依据用户最新要求修正规格及计划，不能只在实现中改一处。小的内部算法、组件私有状态、包版本选择可由实施者解决并记录，无需把每个实现细节再交用户决定。
