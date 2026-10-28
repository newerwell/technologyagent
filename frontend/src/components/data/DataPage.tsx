"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
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
  Page,
  Part,
  QuoteView,
  Supplier,
} from "../../lib/domain-types";
import type { InventorySummary, InventoryView } from "../../lib/inventory-types";
import { formatDateTime, formatNumber } from "../../lib/format";
import { InventoryTable } from "./InventoryTable";
import { QuoteTable } from "./QuoteTable";
import { ReplenishmentPreview } from "./ReplenishmentPreview";
import { SupplierTable } from "./SupplierTable";

const INVENTORY_PAGE_SIZE = 3;
const WAREHOUSES = ["W01", "W02"];
type SessionStatus = "loading" | "ready" | "error";

export function DataPage() {
  const [sessionStatus, setSessionStatus] = useState<SessionStatus>("loading");
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [inventoryLoading, setInventoryLoading] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [inventoryError, setInventoryError] = useState<string | null>(null);
  const [warehouseId, setWarehouseId] = useState("W01");
  const [warehouseOptions, setWarehouseOptions] = useState(WAREHOUSES);
  const [partName, setPartName] = useState("");
  const [page, setPage] = useState(1);
  const [refreshToken, setRefreshToken] = useState(0);
  const [catalogGeneration, setCatalogGeneration] = useState(0);

  const [parts, setParts] = useState<Page<Part> | null>(null);
  const [suppliers, setSuppliers] = useState<Page<Supplier> | null>(null);
  const [quotes, setQuotes] = useState<Page<QuoteView> | null>(null);
  const [inventory, setInventory] = useState<Page<InventoryView> | null>(null);
  const [warnings, setWarnings] = useState<Page<InventoryView> | null>(null);
  const [summary, setSummary] = useState<InventorySummary | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);

  const sessionStatusRef = useRef<SessionStatus>("loading");
  const sessionInFlightRef = useRef<Promise<boolean> | null>(null);

  const setSessionState = useCallback((status: SessionStatus) => {
    sessionStatusRef.current = status;
    setSessionStatus(status);
  }, []);

  const ensureSession = useCallback(async (): Promise<boolean> => {
    if (sessionStatusRef.current === "ready") return true;
    if (sessionInFlightRef.current) return sessionInFlightRef.current;
    setSessionError(null);
    setSessionState("loading");
    const promise = ensureLocalSession()
      .then(() => {
        setSessionState("ready");
        return true;
      })
      .catch((caught) => {
        setSessionState("error");
        setSessionError(caught instanceof Error ? caught.message : "本地会话不可用");
        return false;
      })
      .finally(() => {
        sessionInFlightRef.current = null;
      });
    sessionInFlightRef.current = promise;
    return promise;
  }, [setSessionState]);

  useEffect(() => {
    void ensureSession();
  }, [ensureSession]);

  const handleDataError = useCallback(
    (caught: unknown, setMessage: (message: string | null) => void) => {
      const message = caught instanceof Error ? caught.message : "业务数据加载失败";
      setMessage(message);
      setCatalogGeneration((value) => value + 1);
      if (caught instanceof ApiError && caught.status === 401) {
        setSessionState("error");
        setSessionError("本地会话已失效，请点击刷新数据重新建立会话");
        setCatalogLoading(false);
        setInventoryLoading(false);
      }
    },
    [setSessionState],
  );

  useEffect(() => {
    if (sessionStatus !== "ready") return;
    let active = true;
    setCatalogLoading(true);
    setCatalogError(null);
    setParts(null);
    setSuppliers(null);
    setQuotes(null);
    setCatalogGeneration((value) => value + 1);
    async function load() {
      try {
        const [partsResult, suppliersResult] = await Promise.all([
          getParts({ name: partName || undefined, page_size: 100 }),
          getSuppliers({ page_size: 100 }),
        ]);
        const snapshot = partsResult.meta.data_source === "local_snapshot";
        const quotesResult = snapshot ? null : await getQuotes({ part_name: partName || undefined, page_size: 100 });
        if (!active) return;
        setParts(partsResult.data);
        setSuppliers(suppliersResult.data);
        setQuotes(quotesResult?.data ?? null);
        const sourceWarehouses = partsResult.meta.warehouses;
        if (snapshot && sourceWarehouses?.length) {
          setWarehouseOptions(sourceWarehouses);
          setWarehouseId((current) => sourceWarehouses.includes(current) ? current : sourceWarehouses[0]);
        }
      } catch (caught) {
        if (!active) return;
        handleDataError(caught, setCatalogError);
        setParts(null);
        setSuppliers(null);
        setQuotes(null);
      } finally {
        if (active) setCatalogLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [sessionStatus, partName, refreshToken, handleDataError]);

  useEffect(() => {
    if (sessionStatus !== "ready") return;
    let active = true;
    setInventoryLoading(true);
    setInventoryError(null);
    setInventory(null);
    setWarnings(null);
    setSummary(null);
    setMeta(null);
    async function load() {
      try {
        const [inventoryResult, warningsResult, summaryResult] = await Promise.all([
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
        setInventory(inventoryResult.data);
        setWarnings(warningsResult.data);
        setSummary(summaryResult.data);
        setMeta(inventoryResult.meta);
      } catch (caught) {
        if (!active) return;
        handleDataError(caught, setInventoryError);
        setInventory(null);
        setWarnings(null);
        setSummary(null);
        setMeta(null);
      } finally {
        if (active) setInventoryLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [sessionStatus, warehouseId, partName, page, refreshToken, handleDataError]);

  async function refresh() {
    const wasReady = sessionStatusRef.current === "ready";
    const ok = await ensureSession();
    if (!ok) return;
    if (wasReady) setRefreshToken((value) => value + 1);
  }

  function changeWarehouse(value: string) {
    setWarehouseId(value);
    setPage(1);
  }

  function changePartName(value: string) {
    setPartName(value);
    setPage(1);
  }

  const loading = sessionStatus === "loading" || catalogLoading || inventoryLoading;
  const error = sessionError ?? catalogError ?? inventoryError;

  return (
    <main className="shell">
      <header className="hero data-hero">
        <div>
          <p className="eyebrow">P01 · 本地业务数据</p>
          <h1>采购数据与补货预览</h1>
          <p className="lede">
            查看当前配置的库存与物料来源。缺失字段显示“未知”；目标补货和供应商推荐需要来源提供完整业务数据。
          </p>
        </div>
        <div className="hero-actions">
          <a className="nav-link" href="/">
            返回工程状态
          </a>
          <a className="nav-link" href="/chat">
            进入对话
          </a>
          <button type="button" onClick={() => void refresh()} disabled={loading}>
            {sessionStatus === "loading" ? "连接中…" : loading ? "刷新中…" : "刷新数据"}
          </button>
        </div>
      </header>

      {error ? (
        <section className="alert" role="alert">
          <strong>业务数据加载失败</strong>
          <p>{error}</p>
          <p className="hint">
            错误发生时会清空上一轮数据和金额，不展示过期结果；会话失败后可再次点击刷新重试。
          </p>
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
              {warehouseOptions.map((warehouse) => (
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
          <strong>{formatNumber(summary?.total_available)}</strong>
        </div>
        <div className="stat">
          <span>预计可用</span>
          <strong>{formatNumber(summary?.total_projected)}</strong>
        </div>
        <div className="stat">
          <span>总缺口</span>
          <strong>{formatNumber(summary?.total_shortage)}</strong>
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
              {item.warehouse_id} / {item.part_id} · {item.shortage == null ? `安全库存差额 ${formatNumber(item.safety_shortage)}` : `目标缺口 ${item.shortage}`}
            </span>
          ))}
        </section>
      ) : null}

      <InventoryTable
        page={inventory}
        parts={parts?.records ?? []}
        loading={inventoryLoading}
        onPageChange={setPage}
      />

      {meta?.data_source === "local_snapshot" ? <section className="card wide"><h2>供应商与报价</h2><p>这份库存快照未包含供应商资料和有效报价；不能据此判断报价是否存在。</p></section> : <div className="data-grid">
        <SupplierTable page={suppliers} loading={catalogLoading} />
        <QuoteTable page={quotes} loading={catalogLoading} />
      </div>}

      {meta?.data_source === "local_snapshot" ? <section className="card wide"><h2>本地库存快照</h2><p>快照未提供预留量、在途量、目标库存和有效报价，当前只支持库存查询与安全库存预警。目标补货数量与供应商推荐暂不可计算。</p></section> : <ReplenishmentPreview
        parts={parts?.records ?? []}
        warehouseId={warehouseId}
        catalogGeneration={catalogGeneration}
      />}

      <section className="card wide">
        <h2>本阶段边界</h2>
        <p className="hint">
          当前库存数据源为 {meta?.data_source ?? "未知"}；库存快照只代表采集时刻已保存的记录，不代表完整实时ERP。
          {quoteSummary(quotes)}
        </p>
      </section>

      <footer className="footer">
        <span>库存数据源：{meta?.data_source ?? "未知"}</span>
        <span>
          总在手 {formatNumber(summary?.total_on_hand ?? 0)} · 总预计可用{" "}
          {formatNumber(summary?.total_projected)}
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
