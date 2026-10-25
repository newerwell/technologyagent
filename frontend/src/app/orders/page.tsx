"use client";

import { useCallback, useEffect, useState } from "react";

import { ApprovalCard } from "../../components/approval/ApprovalCard";
import { ApiError, createApprovedOrder, ensureLocalSession, listDrafts, listMutationProposals, listOrders, patchDraft, reconcileOperation, requestApproval, resolveApproval, resolveMutationProposal, resumeOrderRun, startOrderWorkflow, type MutationProposalView, type OrderDraftView, type PurchaseOrderView } from "../../lib/api";

function errorText(error: unknown) {
  return error instanceof ApiError ? `${error.message}（${error.code}）` : error instanceof Error ? error.message : "请求失败";
}

export default function OrdersPage() {
  const [drafts, setDrafts] = useState<OrderDraftView[]>([]);
  const [orders, setOrders] = useState<PurchaseOrderView[]>([]);
  const [proposals, setProposals] = useState<MutationProposalView[]>([]);
  const [warehouseId, setWarehouseId] = useState("");
  const [quantity, setQuantity] = useState(55);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    await ensureLocalSession();
    const [draftResult, orderResult, proposalResult] = await Promise.all([listDrafts(), listOrders({ page: 1, page_size: 100 }), listMutationProposals()]);
    setDrafts(draftResult.data ?? []);
    setOrders(orderResult.data?.records ?? []);
    setProposals(proposalResult.data ?? []);
  }, []);

  async function decideProposal(proposal: MutationProposalView, decision: "approve" | "reject") {
    setBusyId(proposal.approval_id); setError(null);
    try {
      await resolveMutationProposal(proposal.approval_id, decision, proposal.version);
      await refresh();
      setMessages((current) => ({ ...current, [proposal.approval_id]: decision === "approve" ? "提案已批准，可由对应业务工具执行。" : "提案已拒绝，未产生业务变更。" }));
    } catch (caught) { setError(errorText(caught)); }
    finally { setBusyId(null); }
  }

  useEffect(() => { void refresh().catch((caught) => setError(errorText(caught))); }, [refresh]);

  async function prepare() {
    setError(null);
    try {
      const result = await startOrderWorkflow({
        message: "刹车片补到目标库存，7天内到货，生成订单",
        request_id: crypto.randomUUID(),
        draft: { part_ids: ["P001"], ...(warehouseId ? { warehouse_id: warehouseId } : {}), max_lead_days: 7, quantities: { P001: quantity } },
      });
      const threadId = result.data?.thread_id;
      if (!threadId) throw new Error("工作流没有返回会话标识");
      window.location.assign(`/chat?thread=${encodeURIComponent(threadId)}`);
    } catch (caught) { setError(errorText(caught)); }
  }

  async function edit(draft: OrderDraftView) {
    setBusyId(draft.id); setError(null);
    try {
      if (draft.workflow?.pending_interrupt?.kind === "approval") {
        await resumeOrderRun(draft.workflow.run_id, {
          interrupt_id: draft.workflow.pending_interrupt.interrupt_id, decision: "edit",
          expected_version: draft.workflow.pending_interrupt.version,
          payload: { items: draft.items.map((item) => ({ part_id: item.part_id, quote_id: item.quote_id, quantity })) },
          idempotency_key: `edit_${draft.id}_v${draft.version}_${crypto.randomUUID()}`,
        });
        await refresh();
        return;
      }
      const saved = await patchDraft(draft.id, { expected_version: draft.version, items: draft.items.map((item) => ({ part_id: item.part_id, quote_id: item.quote_id, quantity })) });
      const newDraft = saved.data as OrderDraftView;
      setDrafts((current) => current.map((item) => item.id === draft.id ? newDraft : item));
      setQuantity(newDraft.items[0]?.quantity ?? quantity);
    } catch (caught) { setError(errorText(caught)); } finally { setBusyId(null); }
  }

  async function approve(draft: OrderDraftView) {
    setBusyId(draft.id); setError(null);
    try {
      if (draft.workflow?.pending_interrupt?.kind === "approval") {
        await resumeOrderRun(draft.workflow.run_id, {
          interrupt_id: draft.workflow.pending_interrupt.interrupt_id, decision: "approve",
          expected_version: draft.workflow.pending_interrupt.version, payload: {},
          idempotency_key: `approve_${draft.id}_v${draft.version}`,
        });
        await refresh();
        setMessages((current) => ({ ...current, [draft.id]: "已通过原订单工作流处理；状态已刷新。" }));
        return;
      }
      const approval = await requestApproval(draft.id, `ui_${draft.id}`);
      const approvalId = approval.data?.approval_id;
      if (!approvalId) throw new Error("后端未返回审批记录");
      await resolveApproval(approvalId, { interrupt_id: `ui_${draft.id}`, decision: "approve", expected_version: draft.version, idempotency_key: `approve_${draft.id}_v${draft.version}` });
      const created = await createApprovedOrder({ draft_id: draft.id, approval_id: approvalId, idempotency_key: `create_${draft.id}_v${draft.version}` });
      const order = created.data?.order;
      if (!order?.id) throw new Error("订单结果尚未确认，请刷新对账");
      setMessages((current) => ({ ...current, [draft.id]: `已确认订单 ${order.number}` }));
      await refresh();
    } catch (caught) {
      const data = caught instanceof ApiError ? caught.payload?.data as { operation_id?: string } | null : null;
      if (data?.operation_id) {
        try {
          const checked = await reconcileOperation(data.operation_id);
          const outcome = checked.data;
          if (outcome?.status === "succeeded" && outcome.result?.order.id) {
            setMessages((current) => ({ ...current, [draft.id]: `已核对订单 ${outcome.result!.order.number}` }));
            await refresh();
          } else if (outcome?.status === "retryable") {
            setMessages((current) => ({ ...current, [draft.id]: "核对确认事务没有创建订单，可再次使用原幂等请求提交。" }));
          } else {
            setMessages((current) => ({ ...current, [draft.id]: "操作仍在核对中，请刷新订单页查看真实结果。" }));
          }
        } catch (reconcileError) {
          setMessages((current) => ({ ...current, [draft.id]: `结果仍待核对：${errorText(reconcileError)}` }));
        }
      } else {
        setMessages((current) => ({ ...current, [draft.id]: `提交未确认：${errorText(caught)}；刷新后核对订单` }));
      }
    }
    finally { setBusyId(null); }
  }

  async function reject(draft: OrderDraftView) {
    setBusyId(draft.id); setError(null);
    try {
      if (draft.workflow?.pending_interrupt?.kind === "approval") {
        await resumeOrderRun(draft.workflow.run_id, {
          interrupt_id: draft.workflow.pending_interrupt.interrupt_id, decision: "reject",
          expected_version: draft.workflow.pending_interrupt.version, payload: {},
          idempotency_key: `reject_${draft.id}_v${draft.version}`,
        });
        setMessages((current) => ({ ...current, [draft.id]: "已通过原订单工作流拒绝；状态已刷新。" }));
        await refresh();
        return;
      }
      const approval = await requestApproval(draft.id, `ui_${draft.id}`);
      if (!approval.data?.approval_id) throw new Error("后端未返回审批记录");
      await resolveApproval(approval.data.approval_id, { interrupt_id: `ui_${draft.id}`, decision: "reject", expected_version: draft.version, idempotency_key: `reject_${draft.id}_v${draft.version}` });
      setMessages((current) => ({ ...current, [draft.id]: "草稿已拒绝，未创建订单" }));
      await refresh();
    } catch (caught) { setError(errorText(caught)); } finally { setBusyId(null); }
  }

  return <main className="shell">
    <header className="hero data-hero"><div><p className="eyebrow">P04 · 订单与审批</p><h1>采购草稿与人工确认</h1><p className="lede">金额由服务端报价计算；只有明确批准后才创建订单。</p></div><a className="nav-link" href="/chat">返回对话</a></header>
    {error ? <section className="alert" role="alert">{error}</section> : null}
    <section className="card"><h2>开始补货审批流程</h2><p>固定验收案例：P001 刹车片，7 天内到货；字段补充与审批会保存在同一会话中。</p>
      <label>目标数量 <input type="number" min={1} value={quantity} onChange={(event) => setQuantity(Math.max(1, Number(event.target.value)))} /></label>
      <label>仓库编号 <input aria-label="仓库编号" value={warehouseId} onChange={(event) => setWarehouseId(event.target.value)} placeholder="留空以测试补充流程，例如 W01" /></label>
      <button type="button" onClick={() => void prepare()}>开始订单流程</button>
    </section>
    <section><h2>草稿与待审批</h2>{drafts.map((draft) => <ApprovalCard key={draft.id} draft={draft} quantity={quantity} busy={busyId === draft.id} message={messages[draft.id]} onQuantity={setQuantity} onEdit={() => void edit(draft)} onApprove={() => void approve(draft)} onReject={() => void reject(draft)} />)}</section>
    <section><h2>其他业务操作提案</h2>{proposals.length ? proposals.map((proposal) => <article className="card" key={proposal.approval_id}>
      <h3>{proposal.action}</h3><pre>{JSON.stringify(proposal.payload, null, 2)}</pre>
      {proposal.status === "pending" ? <>
        <button type="button" disabled={busyId === proposal.approval_id} onClick={() => void decideProposal(proposal, "approve")}>批准</button>
        <button type="button" disabled={busyId === proposal.approval_id} onClick={() => void decideProposal(proposal, "reject")}>拒绝</button>
      </> : <p>状态：{proposal.status}</p>}
      {messages[proposal.approval_id] ? <p role="status">{messages[proposal.approval_id]}</p> : null}
    </article>) : <p>没有其他待审批操作</p>}</section>
    <section><h2>已创建订单</h2>{orders.length ? <div className="table-wrap"><table><thead><tr><th>订单号</th><th>供应商</th><th>仓库</th><th>金额</th><th>状态</th></tr></thead><tbody>{orders.map((order) => <tr key={order.id} data-testid="order-row"><td>{order.number}</td><td>{order.supplier_id}</td><td>{order.warehouse_id}</td><td>{(order.total_cents / 100).toFixed(2)} 元</td><td>{order.status}</td></tr>)}</tbody></table></div> : <p>尚无订单</p>}</section>
  </main>;
}
