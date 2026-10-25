# 订单审批组件

`ApprovalCard` 展示服务端 OrderDraft 的供应商、仓库、报价、数量、金额、来源、状态和版本；父级提供保存修改、批准、拒绝回调。组件不计算订单总额，也不宣称请求成功。

`SupplementForm` 只渲染服务端 interrupt 指出的缺失字段；当前 MVP 支持补充 `warehouse_id`。

版本更新必须先保存并读取服务器返回的新版本，再允许用户确认。按钮禁用只用于交互防重复，服务端 CAS、批准绑定与幂等仍是最终保障。

P08在订单页增加通用业务提案卡，展示服务端保存的action/payload并提供明确批准/拒绝；卡片调用owner-scoped `/api/mutations/proposals`，UI不直接执行写操作。批准后仍须由同名业务MCP工具以approval_id与幂等键触发MutationService。浏览器回归在`tests/e2e/p08-mutation-proposals.spec.ts`。

验证：`npm --prefix frontend run typecheck`、`npm --prefix frontend run test -- --run`、`npm --prefix frontend run build`、`npm --prefix frontend run test:e2e`。
