# Harness工作流面板

`HarnessPhaseBar`、`PlanPanel`、`ReviewPanel`消费事件reducer和持久RunView的结构字段，不从消息文本猜阶段。waiting_input显示人工等待；Run.status失败/取消优先于phase=result。计划显示步骤状态和来源，评审展示check id、原因、引用及修订计数。

面板不展示模型提示词或私有推理。事件重放和RunView快照均由`useChat`合并，使刷新后的阶段、计划和评审可以恢复。审批中断和既有订单卡片继续由P04组件处理。

检查：`npm --prefix frontend run typecheck`、`npm --prefix frontend run test -- --run`；浏览器验收见`tests/e2e/chat-flow.spec.ts`。
