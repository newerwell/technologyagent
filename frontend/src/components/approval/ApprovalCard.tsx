"use client";

import type { OrderDraftView } from "../../lib/api";

type Props = {
  draft: OrderDraftView;
  quantity: number;
  busy: boolean;
  message?: string;
  onQuantity: (value: number) => void;
  onEdit: () => void;
  onApprove: () => void;
  onReject: () => void;
};

export function ApprovalCard({ draft, quantity, busy, message, onQuantity, onEdit, onApprove, onReject }: Props) {
  const item = draft.items[0];
  return (
    <article className="card approval-card" data-testid="approval-card">
      <header><h2>采购草稿 · {draft.id.slice(-8)}</h2><span className="pill">版本 {draft.version}</span></header>
      <p>供应商 {draft.supplier_id} · 仓库 {draft.warehouse_id}</p>
      <div className="table-wrap"><table><thead><tr><th>零件</th><th>报价</th><th>单价</th><th>数量</th><th>小计</th></tr></thead>
        <tbody>{draft.items.map((line) => <tr key={`${line.part_id}:${line.quote_id}`}>
          <td>{line.part_id}</td><td>{line.quote_id}</td><td>{(line.unit_price_cents / 100).toFixed(2)} 元</td>
          <td>{draft.items.length === 1 && ["draft", "pending_approval"].includes(draft.state) ? <input aria-label="采购数量" type="number" min={1} value={quantity} onChange={(event) => onQuantity(Math.max(1, Number(event.target.value)))} /> : line.quantity}</td>
          <td>{(line.line_total_cents / 100).toFixed(2)} 元</td>
        </tr>)}</tbody></table></div>
      <p className="total">服务端总额：{(draft.total_cents / 100).toFixed(2)} 元</p>
      <p className="hint">来源：{draft.source_refs.map((ref) => `${ref.entity}:${ref.id}`).join("、") || "无"}</p>
      {message ? <p role="status">{message}</p> : null}
      <footer>
        {draft.state === "draft" || draft.state === "pending_approval" ? <button type="button" onClick={onEdit} disabled={busy}>保存修改并重新确认</button> : null}
        {draft.state === "draft" || draft.state === "pending_approval" ? <>
          <button type="button" onClick={onApprove} disabled={busy}>批准并创建订单</button>
          <button type="button" onClick={onReject} disabled={busy}>拒绝</button>
        </> : null}
        <span className="pill">{draft.state}</span>
      </footer>
    </article>
  );
}
