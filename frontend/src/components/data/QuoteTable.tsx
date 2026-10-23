"use client";

import type { Page, QuoteView } from "../../lib/domain-types";
import { formatDateTime, formatMoney } from "../../lib/format";

type Props = {
  page: Page<QuoteView> | null;
  loading: boolean;
};

export function QuoteTable({ page, loading }: Props) {
  const records = page?.records ?? [];
  return (
    <section className="card" aria-label="报价">
      <div className="section-title">
        <h2>报价</h2>
        <span className="pill">{page?.total ?? 0} 条</span>
      </div>
      <div className="table-scroll">
        <table className="data-table" data-testid="quote-table">
          <thead>
            <tr>
              <th>报价</th>
              <th>物料</th>
              <th>供应商</th>
              <th>单价</th>
              <th>MOQ</th>
              <th>交期</th>
              <th>有效期至</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {records.map((item) => (
              <tr key={item.id}>
                <td>{item.id}</td>
                <td>{item.part_name}</td>
                <td>{item.supplier_name}</td>
                <td className="money">{formatMoney(item.unit_price_cents)}</td>
                <td>{item.min_order_qty}</td>
                <td>{item.lead_days} 天</td>
                <td>{formatDateTime(item.valid_until)}</td>
                <td>
                  <span className={item.is_valid ? "badge badge-ok" : "badge badge-error"}>
                    {item.is_valid ? "有效" : "失效"}
                  </span>
                  <span className="muted"> {item.supplier_status === "active" ? "合作中" : "供应商停用"}</span>
                </td>
              </tr>
            ))}
            {records.length === 0 ? (
              <tr>
                <td colSpan={8} className="empty-cell">
                  {loading ? "加载中…" : "没有匹配的报价"}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}
