"use client";

import { useEffect, useState } from "react";

import {
  ensureLocalSession,
  getInventory,
  getInventorySummary,
  getInventoryWarnings,
  getParts,
  getQuotes,
  getSuppliers,
  type Meta,
} from "../../lib/api";
import type {
  InventorySummary,
  InventoryView,
  Page,
  Part,
  QuoteView,
  Supplier,
} from "../../lib/domain-types";
import { formatDateTime, formatNumber } from "../../lib/format";
import { InventoryTable } from "./InventoryTable";
import { QuoteTable } from "./QuoteTable";
import { ReplenishmentPreview } from "./ReplenishmentPreview";
import { SupplierTable } from "./SupplierTable";

const INVENTORY_PAGE_SIZE = 3;
const WAREHOUSES = ["W01", "W02"];

export function DataPage() {
  const [sessionReady, setSessionReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [warehouseId, setWarehouseId] = useState("W01");
  const [partName, setPartName] = useState("");
  const [page, setPage] = useState(1);
  const [refreshToken, setRefreshToken] = useState(0);

  const [parts, setParts] = useState<Page<Part> | null>(null);
  const [suppliers, setSuppliers] = useState<Page<Supplier> | null>(null);
  const [quotes, setQuotes] = useState<Page<QuoteView> | null>(null);
  const [inventory, setInventory] = useState<Page<InventoryView> | null>(null);
  const [warnings, setWarnings] = useState<Page<InventoryView> | null>(null);
  const [summary, setSummary] = useState<InventorySummary | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);

  useEffect(() => {
    let active = true;
    ensureLocalSession()
      .then(() => {
        if (active) setSessionReady(true);
      })
      .catch((caught) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "本地会话不可用");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!sessionReady) return;
    let active = true;
    async function load() {
      setLoading(true);
      setError(null);
      setParts(null);
      setSuppliers(null);
      setQuotes(null);
      setInventory(null);
      setWarnings(null);
      setSummary(null);
      setMeta(null);
      try {
        const [
          partsResult,
          suppliersResult,
          quotesResult,
          inventoryResult,
          warningsResult,
          summaryResult,
        ] = await Promise.all([
          getParts({ name: partName || undefined, page_size: 100 }),
          getSuppliers({ page_size: 100 }),
          getQuotes({ part_name: partName || undefined, page_size: 100 }),
          getInventory({
            warehouse_id: warehouseId,
            part_name: partName || undefined,
            page,
            page_size: INVENTORY_PAGE_SIZE,
          }),
          getInventoryWarnings({
            warehouse_id: warehouseId,
            part_name: partName || undefined,
            page_size: 100,
          }),
          getInventorySummary({ warehouse_id: warehouseId }),
        ]);
        if (!active) return;
        setParts(partsResult.data);
        setSuppliers(suppliersResult.data);
        setQuotes(quotesResult.data);
        setInventory(inventoryResult.data);
        setWarnings(warningsResult.data);
        setSummary(summaryResult.data);
        setMeta(inventoryResult.meta);
      } catch (caught) {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "业务数据加载失败");
        setParts(null);
        setSuppliers(null);
        setQuotes(null);
        setInventory(null);
        setWarnings(null);
        setSummary(null);
        setMeta(null);
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [sessionReady, warehouseId, partName, page, refreshToken]);

  function changeWarehouse(value: string) {
    setWarehouseId(value);
    setPage(1);
  }

  function changePartName(value: string) {
    setPartName(value);
    setPage(1);
  }

  return (
    <main className="shell">
      <header className="hero data-hero">
        <div>
          <p className="eyebrow">P01 · 本地业务数据</p>
          <h1>采购数据与补货预览</h1>
          <p className="lede">
            查看合成库存、供应商与报价，并按确定性规则计算补货缺口和建议。金额全部为整数分，
            页面不自行实现补货公式；本阶段不接模型、不创建订单。
          </p>
        </div>
        <div className="hero-actions">
          <a className="nav-link" href="/">
            返回工程状态
          </a>
          <button type="button" onClick={() => setRefreshToken((value) => value + 1)} disabled={loading}>
            {loading ? "刷新中…" : "刷新数据"}
          </button>
        </div>
      </header>

      {error ? (
        <section className="alert" role="alert">
          <strong>业务数据加载失败</strong>
          <p>{error}</p>
          <p className="hint">错误发生时会清空上一轮数据和金额，不展示过期结果。</p>
        </section>
      ) : null}

      <section className="card wide" aria-label="筛选">
        <div className="filter-row">
          <label>
            仓库
            <select
              aria-label="筛选仓库"
              value={warehouseId}
              onChange={(event) => changeWarehouse(event.target.value)}
            >
              {WAREHOUSES.map((warehouse) => (
                <option key={warehouse} value={warehouse}>
                  {warehouse}
                </option>
              ))}
            </select>
          </label>
          <label>
            物料名称
            <input
              aria-label="物料名称"
              placeholder="例如：刹车片"
              value={partName}
              onChange={(event) => changePartName(event.target.value)}
            />
          </label>
          <span className="pill">来源 {meta?.data_source ?? "-"}</span>
          <span className="pill">as_of {formatDateTime(meta?.as_of)}</span>
        </div>
      </section>

      <section className="stat-grid" aria-label="库存汇总">
        <div className="stat">
          <span>库存记录</span>
          <strong>{formatNumber(summary?.records ?? 0)}</strong>
        </div>
        <div className="stat">
          <span>在手</span>
          <strong>{formatNumber(summary?.total_on_hand ?? 0)}</strong>
        </div>
        <div className="stat">
          <span>可用</span>
          <strong>{formatNumber(summary?.total_available ?? 0)}</strong>
        </div>
        <div className="stat">
          <span>预计可用</span>
          <strong>{formatNumber(summary?.total_projected ?? 0)}</strong>
        </div>
        <div className="stat">
          <span>总缺口</span>
          <strong>{formatNumber(summary?.total_shortage ?? 0)}</strong>
        </div>
        <div className="stat">
          <span>预警</span>
          <strong>{formatNumber(summary?.warning_count ?? 0)}</strong>
        </div>
      </section>

      {warnings && warnings.records.length > 0 ? (
        <section className="warning-strip" aria-label="预警列表">
          <strong>当前预警 {warnings.total} 条：</strong>
          {warnings.records.map((item) => (
            <span key={item.id} className="badge badge-error">
              {item.warehouse_id} / {item.part_id} · 缺口 {item.shortage}
            </span>
          ))}
        </section>
      ) : null}

      <InventoryTable
        page={inventory}
        parts={parts?.records ?? []}
        loading={loading}
        onPageChange={setPage}
      />

      <div className="data-grid">
        <SupplierTable page={suppliers} loading={loading} />
        <QuoteTable page={quotes} loading={loading} />
      </div>

      <ReplenishmentPreview parts={parts?.records ?? []} warehouseId={warehouseId} />

      <section className="card wide">
        <h2>本阶段边界</h2>
        <p className="hint">
          当前数据源为 local_seed；报价有效性由后端按当前时间与供应商状态判断。
          {quoteSummary(quotes)}
        </p>
      </section>

      <footer className="footer">
        <span>数据源：local_seed（合成 fixtures/v1）</span>
        <span>
          总在手 {formatNumber(summary?.total_on_hand ?? 0)} · 总预计可用{" "}
          {formatNumber(summary?.total_projected ?? 0)}
        </span>
      </footer>
    </main>
  );
}

function quoteSummary(page: Page<QuoteView> | null): string {
  if (!page) return "";
  const valid = page.records.filter((quote) => quote.is_valid).length;
  return " 当前 " + page.total + " 条报价中 " + valid + " 条有效。";
}
