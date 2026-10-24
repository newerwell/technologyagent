# 交给其他 Agent 的实施入口

状态：P00/P01/P02原关闭项未发现倒退；P05补修已关闭部分原反例。P06已实现上传，但独立审查7项缺口及Linux CI失败，前置事实/验收和订单修订/恢复仍有残留。

当前入口：[P06及前置补修计划](./P06-followup.md) F01–F09及文末提示词；依据[P06独立审查](../reviews/2026-10-24-P06-review.md)。不开始P07，旧标签不移动，不能仅补报告打开就宣布P06完成。

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

当前直接复制 [P06及前置补修计划](./P06-followup.md)文末提示词。以后按 STATUS 选择阶段；不一次要求一个Agent把P00–P09全部做完。这样每阶段都保留独立可审查、可运行、可上传的结果。

任务中的文件、函数和命令均是**要创建的目标**。文档中的assert是验收样例，不表示这些函数或测试已存在。库的内部调用以P00实测锁定版本为准；应用端口、数据字段、错误语义和阶段范围按本计划固定。

规格决定做什么，实施计划决定怎么拆和怎么验证。若出现冲突，先依据用户最新要求修正规格及计划，不能只在实现中改一处。小的内部算法、组件私有状态、包版本选择可由实施者解决并记录，无需把每个实现细节再交用户决定。
