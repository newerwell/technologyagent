"use client";

import { useEffect, useState } from "react";
import { ApiError, deletePreference, ensureLocalSession, getPreferences, rememberPreference, type ExplicitPreferences } from "../../lib/api";

const labels: Array<{ key: keyof ExplicitPreferences; label: string; placeholder: string }> = [
  { key: "default_warehouse", label: "默认仓库", placeholder: "例如 W01" },
  { key: "preferred_supplier", label: "偏好供应商", placeholder: "例如 S01" },
  { key: "max_lead_days", label: "最长交期（天）", placeholder: "例如 7" },
];

export default function PreferencesPage() {
  const [values, setValues] = useState<ExplicitPreferences>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("正在读取已明确记住的偏好…");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  async function reload() {
    setLoading(true);
    try {
      await ensureLocalSession();
      const response = await getPreferences();
      const current = response.data ?? {};
      setValues(current);
      setDrafts(Object.fromEntries(Object.entries(current).map(([key, value]) => [key, String(value)])));
      setMessage("偏好已从当前账号读取。");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "读取偏好失败。");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { void reload(); }, []);
  async function save(key: keyof ExplicitPreferences) {
    const raw = drafts[key] ?? "";
    const value = key === "max_lead_days" ? Number(raw) : raw.trim();
    setBusy(true);
    try {
      await rememberPreference(key, value);
      await reload();
      setMessage("已按你的明确要求记住该偏好。");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "保存偏好失败。");
    } finally { setBusy(false); }
  }
  async function clear(key: keyof ExplicitPreferences) {
    setBusy(true);
    try { await deletePreference(key); await reload(); setMessage("偏好已删除。"); }
    catch (error) { setMessage(error instanceof ApiError ? error.message : "删除偏好失败。"); }
    finally { setBusy(false); }
  }
  return <main className="page-shell">
    <header className="page-header"><div><p className="eyebrow">TechnologyAgent · P07</p><h1>明确偏好</h1><p>只有点击“记住”才会保存；本轮明确指定的条件优先于这里的设置。</p></div>
      <nav aria-label="主导航"><a href="/chat">对话</a>　<a href="/orders">订单</a>　<a href="/preferences" aria-current="page">偏好</a></nav></header>
    <section className="panel"><p role="status">{message}</p>{labels.map(({ key, label, placeholder }) => <div className="form-row" key={key}>
      <label htmlFor={key}>{label}</label><input id={key} disabled={loading} value={drafts[key] ?? ""} placeholder={placeholder} onChange={(event) => setDrafts({ ...drafts, [key]: event.target.value })} />
      <span>{values[key] === undefined ? "尚未记住" : `已记住：${values[key]}`}</span>
      <button disabled={loading || busy || !(drafts[key] ?? "").trim()} onClick={() => void save(key)}>记住</button>
      <button disabled={loading || busy || values[key] === undefined} onClick={() => void clear(key)}>删除</button>
    </div>)}</section>
  </main>;
}
