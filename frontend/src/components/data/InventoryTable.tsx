"use client";

import type { Page, Part } from "../../lib/domain-types";
import type { InventoryView } from "../../lib/inventory-types";
import { formatNumber } from "../../lib/format";

type Props = {
  page: Page<InventoryView> | null;
  parts: Part[];
  loading: boolean;
  onPageChange: (page: number) => void;
};

export function InventoryTable({ page, parts, loading, onPageChange }: Props) {
  const partNames = new Map(parts.map((part) => [part.id, part.name]));
  const records = page?.records ?? [];
  return (
    <section className="card wide" aria-label="库存">
      <div className="section-title">
        <div>
          <h2>库存</h2>
          <p className="hint">数据来源见页面标识；“未知”表示来源未提供该字段。库存快照的预警按在手量与安全库存比较，目标补货缺口需要完整库存字段。</p>
        </div>
        <span className="pill">每页 {page?.page_size ?? 3} 条</span>
      </div>
      <div className="table-scroll">
        <table className="data-table" data-testid="inventory-table">
          <thead>
            <tr>
              <th>仓库</th>
              <th>物料</th>
              <th>在手</th>
              <th>预留</th>
              <th>在途</th>
              <th>可用</th>
              <th>预计</th>
              <th>安全库存</th>
              <th>目标</th>
              <th>缺口</th>
              <th>状态</th>
              <th>版本</th>
            </tr>
          </thead>
          <tbody>
            {records.map((item) => (
              <tr key={item.id}>
                <td>{item.warehouse_id}</td>
                <td>
                  <strong>{item.part_id}</strong>
                  <span className="muted"> {partNames.get(item.part_id) ?? item.part_name ?? ""}</span>
                </td>
                <td>{formatNumber(item.on_hand)}</td>
                <td>{formatNumber(item.reserved)}</td>
                <td>{formatNumber(item.inbound)}</td>
                <td>{formatNumber(item.available)}</td>
                <td>{formatNumber(item.projected)}</td>
                <td>{formatNumber(item.safety_stock)}</td>
                <td>{formatNumber(item.target_stock)}</td>
                <td>{formatNumber(item.shortage)}</td>
                <td>
                  <span className={item.warning ? "badge badge-error" : "badge badge-ok"}>
                    {item.warning ? "预警" : "正常"}
                  </span>
                </td>
                <td>{item.version ?? "未知"}</td>
              </tr>
            ))}
            {records.length === 0 ? (
              <tr>
                <td colSpan={12} className="empty-cell">
                  {loading ? "加载中…" : "没有匹配的库存记录"}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <div className="page-nav">
        <button
          type="button"
          onClick={() => onPageChange((page?.page ?? 1) - 1)}
          disabled={loading || !page || page.page <= 1}
        >
          上一页
        </button>
        <span>
          第 {page?.page ?? 0} / {page?.pages ?? 0} 页 · 共 {page?.total ?? 0} 条
        </span>
        <button
          type="button"
          onClick={() => onPageChange((page?.page ?? 1) + 1)}
          disabled={loading || !page || page.page >= page.pages}
        >
          下一页
        </button>
      </div>
    </section>
  );
}
