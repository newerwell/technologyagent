"use client";

import type { Page, Supplier } from "../../lib/domain-types";

type Props = {
  page: Page<Supplier> | null;
  loading: boolean;
};

export function SupplierTable({ page, loading }: Props) {
  const records = page?.records ?? [];
  return (
    <section className="card" aria-label="供应商">
      <div className="section-title">
        <h2>供应商</h2>
        <span className="pill">{page?.total ?? 0} 家</span>
      </div>
      <div className="table-scroll">
        <table className="data-table" data-testid="supplier-table">
          <thead>
            <tr>
              <th>编号</th>
              <th>名称</th>
              <th>状态</th>
              <th>信用</th>
            </tr>
          </thead>
          <tbody>
            {records.map((item) => (
              <tr key={item.id}>
                <td>{item.code}</td>
                <td>{item.name}</td>
                <td>
                  <span className={item.status === "active" ? "badge badge-ok" : "badge badge-muted"}>
                    {item.status === "active" ? "合作中" : "停用"}
                  </span>
                </td>
                <td>{item.credit_rating ?? "-"}</td>
              </tr>
            ))}
            {records.length === 0 ? (
              <tr>
                <td colSpan={4} className="empty-cell">
                  {loading ? "加载中…" : "没有匹配的供应商"}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}
