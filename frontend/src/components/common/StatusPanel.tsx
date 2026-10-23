"use client";

import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  createLocalSession,
  getHealth,
  getMe,
  getReady,
  type CheckState,
  type Envelope,
  type HealthData,
  type ReadyData,
  type WhoAmIData,
} from "../../lib/api";

type ReadyView = {
  envelope: Envelope<ReadyData> | null;
  error: ApiError | null;
};

type Status = "loading" | "ok" | "error";

function statusLabel(status: string | undefined): string {
  if (!status) return "未知";
  if (status === "ok") return "正常";
  if (status === "disabled") return "未启用";
  if (status === "unavailable") return "不可用";
  return status;
}

function statusClass(status: string | undefined): string {
  if (status === "ok" || status === "ready") return "badge badge-ok";
  if (status === "disabled") return "badge badge-muted";
  return "badge badge-error";
}

function checkDetail(check: CheckState | undefined): string {
  if (!check) return "无数据";
  return check.detail ?? check.reason ?? "";
}

export function StatusPanel() {
  const [loading, setLoading] = useState(true);
  const [health, setHealth] = useState<HealthData | null>(null);
  const [ready, setReady] = useState<ReadyView | null>(null);
  const [session, setSession] = useState<WhoAmIData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [lastCheckedAt, setLastCheckedAt] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setSessionError(null);
    try {
      const healthEnvelope = await getHealth();
      setHealth(healthEnvelope.data);
    } catch (caught) {
      setHealth(null);
      setError(caught instanceof Error ? caught.message : "后端不可用");
      setLoading(false);
      return;
    }

    try {
      const readyEnvelope = await getReady();
      setReady({ envelope: readyEnvelope, error: null });
    } catch (caught) {
      if (caught instanceof ApiError) {
        setReady({ envelope: (caught.payload as Envelope<ReadyData> | null) ?? null, error: caught });
      } else {
        setReady({
          envelope: null,
          error: new ApiError("NETWORK_ERROR", "无法读取就绪状态", 0, true),
        });
      }
    }

    try {
      let me: Envelope<WhoAmIData>;
      try {
        me = await getMe();
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 401) {
          await createLocalSession();
          me = await getMe();
        } else {
          throw caught;
        }
      }
      setSession(me.data);
    } catch (caught) {
      setSession(null);
      setSessionError(caught instanceof Error ? caught.message : "本地会话不可用");
    }

    setLastCheckedAt(new Date().toLocaleString("zh-CN", { hour12: false }));
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const checks = ready?.envelope?.data?.checks ?? {};
  const readyStatus = ready?.envelope?.data?.status;

  return (
    <main className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">P00 · 工程底座</p>
          <h1>TechnologyAgent</h1>
          <p className="lede">
            采购 Agent 的本地工程底座。当前阶段只提供配置、健康检查、MongoDB 事务能力和本地会话，
            不包含采购查询、聊天、真实模型、订单或沙箱功能。
          </p>
        </div>
        <div className="hero-actions">
          <span className={statusClass(health ? "ok" : error ? "unavailable" : undefined)}>
            {loading ? "检测中" : health ? "后端已连接" : "后端不可用"}
          </span>
          <button type="button" onClick={() => void load()} disabled={loading}>
            {loading ? "正在刷新…" : "重新检测"}
          </button>
        </div>
      </header>

      {error ? (
        <section className="alert" role="alert">
          <strong>无法连接后端</strong>
          <p>{error}</p>
          <p className="hint">请运行 start.ps1，并确认 API_PORT 未被占用。</p>
        </section>
      ) : null}

      <section className="grid" aria-label="运行状态">
        <article className="card">
          <h2>API 存活</h2>
          <p className={statusClass(health ? "ok" : undefined)}>
            {health ? "正常" : loading ? "检测中" : "不可用"}
          </p>
          <dl>
            <div>
              <dt>组件</dt>
              <dd>{health?.component ?? "-"}</dd>
            </div>
            <div>
              <dt>应用</dt>
              <dd>{health?.app ?? "-"}</dd>
            </div>
          </dl>
        </article>

        <article className="card">
          <h2>依赖就绪</h2>
          <p className={statusClass(readyStatus)}>
            {readyStatus === "ready" ? "就绪" : readyStatus ? "降级" : loading ? "检测中" : "不可用"}
          </p>
          <dl>
            <div>
              <dt>数据库</dt>
              <dd>
                <span className={statusClass(checks.db?.status)}>
                  {statusLabel(checks.db?.status)}
                </span>
                <span className="detail"> · {checkDetail(checks.db)}</span>
              </dd>
            </div>
            <div>
              <dt>事务能力</dt>
              <dd>
                <span className={statusClass(checks.transaction?.status)}>
                  {statusLabel(checks.transaction?.status)}
                </span>
                <span className="detail"> · {checkDetail(checks.transaction)}</span>
              </dd>
            </div>
            <div>
              <dt>模型</dt>
              <dd>
                <span className={statusClass(checks.model?.status)}>
                  {statusLabel(checks.model?.status)}
                </span>
                <span className="detail"> · {checkDetail(checks.model)}</span>
              </dd>
            </div>
          </dl>
          {ready?.error ? <p className="hint">{ready.error.message}</p> : null}
        </article>

        <article className="card">
          <h2>可信上下文</h2>
          <p className={statusClass(session ? "ok" : sessionError ? "unavailable" : undefined)}>
            {session ? "本地会话已建立" : sessionError ? "会话不可用" : loading ? "检测中" : "未建立"}
          </p>
          <dl>
            <div>
              <dt>owner</dt>
              <dd>{session?.owner_id ?? "-"}</dd>
            </div>
            <div>
              <dt>身份来源</dt>
              <dd>服务端 Cookie（不使用请求体 owner_id）</dd>
            </div>
          </dl>
          {sessionError ? <p className="hint">{sessionError}</p> : null}
        </article>
      </section>

      <section className="card wide" aria-label="能力状态">
        <h2>能力矩阵</h2>
        <div className="capabilities">
          {Object.entries(checks).map(([name, check]) => (
            <div className="capability" key={name}>
              <span>{name}</span>
              <span className={statusClass(check.status)}>{statusLabel(check.status)}</span>
              <small>{checkDetail(check)}</small>
            </div>
          ))}
          {Object.keys(checks).length === 0 ? <p className="hint">尚未收到 /ready 响应。</p> : null}
        </div>
        <p className="hint">
          MCP 与沙箱在后续阶段交付；P00 不调用真实模型，也不读写业务数据。
        </p>
      </section>

      <footer className="footer">
        <span>上次检测：{lastCheckedAt ?? "尚未完成"}</span>
        <span>API 同源代理：/health、/ready、/api/*</span>
      </footer>
    </main>
  );
}
