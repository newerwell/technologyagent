# API routes

## Responsibilities

`mutations.py` exposes the owner-scoped HTTP surface for preparing, listing, and resolving generic business-operation proposals. It calls `ApprovalService`; approving a proposal does not execute its business mutation. The corresponding approved MCP business tool performs the transaction.

## Public endpoints

- `POST /api/mutations/proposals` — create a proposal from `{ action, payload }`.
- `GET /api/mutations/proposals` — list the current owner's proposals.
- `POST /api/mutations/proposals/{approval_id}/resolve` — approve or reject with `decision_key` and `expected_version`.

The owner comes from the local session cookie, never from the request body. Actions outside the allowlist return `UNSUPPORTED_OPERATION`; missing/expired sessions return `UNAUTHENTICATED`; stale or conflicting decisions return `IDEMPOTENCY_CONFLICT`. Proposal listing and decisions are scoped by both owner and approval ID.

## Example

```http
POST /api/mutations/proposals
Content-Type: application/json

{"action":"supplier_create","payload":{"code":"SUP-NEW","name":"测试供应商"}}
```

## Verification and limits

The UI regression is `tests/e2e/p08-mutation-proposals.spec.ts`; API and transactional behavior is covered by `tests/integration/test_business_mutations.py` and `test_inventory_receipts.py`. The local API does not itself connect to a real ERP or execute a write when a proposal is approved.

P08 通用业务提案在订单页共享呈现、批准/拒绝并通过 /api/mutations/proposals/{approval_id}/execute 执行服务端持久化 payload；执行请求只收幂等键，不接受替换业务字段。执行成功后显示 consumed 并从列表中移除可执行按钮。
P08 analyst/order 图角色可发现 proposal-only `mutation_prepare`，但不获直接业务写工具。写动作由已批准proposal的服务端payload消费；当前远程ERP写能力继续关闭。
通用业务提案归属于创建者 owner，不绑定创建它的 run：同一 owner 可从新会话或订单页继续已批准提案；其他 owner 无法列出、决定或执行该提案。执行通过 owner-scoped approval 与持久幂等键保证单次业务效果。订单草稿审批/恢复仍由其原 run 工作流约束。
