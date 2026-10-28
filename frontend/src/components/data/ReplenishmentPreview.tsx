"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { previewReplenishment, type Meta } from "../../lib/api";
import type { Part, PreviewResult } from "../../lib/domain-types";
import { formatDateTime, formatMoney, formatNumber } from "../../lib/format";

type Props = {
  parts: Part[];
  warehouseId: string;
  catalogGeneration: number;
};

export function ReplenishmentPreview({
  parts,
  warehouseId,
  catalogGeneration,
}: Props) {
  const [selectedPartId, setSelectedPartId] = useState("");
  const [maxLeadDays, setMaxLeadDays] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const requestIdRef = useRef(0);
  const partsSignature = parts.map((part) => part.id + ":" + part.name).join("|");

  const invalidatePreview = useCallback(() => {
    requestIdRef.current += 1;
    setLoading(false);
    setPreview(null);
    setMeta(null);
    setError(null);
  }, []);

  useEffect(() => {
    invalidatePreview();
    if (parts.length === 0) {
      setSelectedPartId("");
      return;
    }
    if (!parts.some((part) => part.id === selectedPartId)) {
      setSelectedPartId(parts[0].id);
    }
    // selectedPartId intentionally not a dep: a selection change is handled by its event.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [warehouseId, catalogGeneration, partsSignature, invalidatePreview]);

  async function submit() {
    if (!selectedPartId) {
      setError("请选择物料");
      setPreview(null);
      return;
    }
    const trimmed = maxLeadDays.trim();
    const numeric = trimmed === "" ? null : Number(trimmed);
    if (numeric !== null && (!Number.isInteger(numeric) || numeric < 0)) {
      setError("最大交期必须是非负整数");
      setPreview(null);
      return;
    }
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setLoading(true);
    setError(null);
    setPreview(null);
    setMeta(null);
    try {
      const envelope = await previewReplenishment({
        part_ids: [selectedPartId],
        warehouse_id: warehouseId,
        max_lead_days: numeric,
      });
      if (requestId !== requestIdRef.current) return;
      setPreview(envelope.data);
      setMeta(envelope.meta);
    } catch (caught) {
      if (requestId !== requestIdRef.current) return;
      setError(caught instanceof Error ? caught.message : "补货预览失败");
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }

  const line = preview?.lines[0];
  const missingFields = line?.missing_fields ?? [];
  const candidates = line?.candidate_quotes ?? [];

  return (
    <section className="card wide" aria-label="补货预览">
      <div className="section-title">
        <div>
          <h2>补货预览</h2>
          <p className="hint">由后端纯函数计算；浏览器不计算缺口、MOQ 或金额。</p>
        </div>
        <span className="pill">API: /api/replenishment/preview</span>
      </div>

      <div className="filter-row">
        <label>
          物料
          <select
            aria-label="预览物料"
            value={selectedPartId}
            onChange={(event) => {
              invalidatePreview();
              setSelectedPartId(event.target.value);
            }}
          >
            {parts.map((part) => (
              <option key={part.id} value={part.id}>
                {part.id} · {part.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          仓库
          <input aria-label="预览仓库" value={warehouseId} readOnly />
        </label>
        <label>
          最大交期（天）
          <input
            aria-label="最大交期"
            inputMode="numeric"
            placeholder="不限制"
            value={maxLeadDays}
            onChange={(event) => {
              setMaxLeadDays(event.target.value);
              invalidatePreview();
            }}
          />
        </label>
        <button type="button" onClick={() => void submit()} disabled={loading || !selectedPartId}>
          {loading ? "计算中…" : "生成补货预览"}
        </button>
      </div>

      {error ? (
        <p className="alert" role="alert">
          {error}
        </p>
      ) : null}

      {line ? (
        <div className="preview-result">
          <div className="stat-grid">
            <div className="stat">
              <span>可用量</span>
              <strong>{formatNumber(line.available)}</strong>
            </div>
            <div className="stat">
              <span>预计可用量</span>
              <strong>{formatNumber(line.projected)}</strong>
            </div>
            <div className="stat">
              <span>缺口</span>
              <strong>{formatNumber(line.shortage)}</strong>
            </div>
            <div className="stat">
              <span>建议数量</span>
              <strong>{formatNumber(line.quantity)}</strong>
            </div>
            <div className="stat">
              <span>推荐总额</span>
              <strong className="money" data-testid="preview-total">
                {formatMoney(line.total_cents)}
              </strong>
            </div>
          </div>
          <p>
            {line.recommended_quote_id ? (
              <span className="badge badge-ok">推荐报价 {line.recommended_quote_id}</span>
            ) : (
              <span className="badge badge-error">无可确认推荐</span>
            )}
            {line.warning ? <span className="badge badge-error">低于安全库存</span> : null}
            {line.actionable ? (
              <span className="badge badge-muted">仅预览，不创建订单</span>
            ) : (
              <span className="badge badge-error">不可下单</span>
            )}
            {missingFields.length > 0 ? (
              <span className="hint"> 缺失：{missingFields.map((field) =>
                field === "part_inactive" ? "物料已停用" : field
              ).join("、")}</span>
            ) : null}
          </p>
          {candidates.length > 0 ? (
            <div className="table-scroll">
              <table className="data-table" data-testid="candidate-table">
                <thead>
                  <tr>
                    <th>报价</th>
                    <th>供应商</th>
                    <th>单价</th>
                    <th>MOQ</th>
                    <th>交期</th>
                    <th>建议数量</th>
                    <th>行金额</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((quote) => (
                    <tr key={quote.quote_id}>
                      <td>{quote.quote_id}</td>
                      <td>{quote.supplier_name}</td>
                      <td className="money">{formatMoney(quote.unit_price_cents)}</td>
                      <td>{quote.min_order_qty}</td>
                      <td>{quote.lead_days} 天</td>
                      <td>{quote.suggested_quantity}</td>
                      <td className="money">{formatMoney(quote.line_total_cents)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <p className="hint">
            数据源：{meta?.data_source ?? "-"} · as_of：{formatDateTime(meta?.as_of)}
          </p>
        </div>
      ) : null}
    </section>
  );
}
