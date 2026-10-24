import type { PlanItem } from "../../lib/events";

const statusText: Record<NonNullable<PlanItem["status"]>, string> = {
  pending: "待执行", running: "执行中", done: "完成", failed: "失败", skipped: "跳过",
};

export function PlanPanel({ items }: { items: PlanItem[] }) {
  if (!items.length) return null;
  return <section className="card workflow-panel" aria-label="执行计划" data-testid="plan-panel">
    <h2>执行计划</h2>
    <ol>{items.map((item) => <li key={item.id}>
      <strong>{item.title}</strong> <span>{statusText[item.status ?? "pending"]}</span>
      {item.evidence_refs?.length ? <small>依据：{item.evidence_refs.map((ref) => `${ref.entity}/${ref.id}`).join("、")}</small> : null}
      {item.query_evidence?.length ? <small>查询依据：{item.query_evidence.map((ref) => `${ref.tool_name}（${ref.total ?? "未知条数"}条，${Object.entries(ref.arguments ?? {}).map(([key, value]) => `${key}=${String(value)}`).join("、")}）`).join("；")}</small> : null}
    </li>)}</ol>
  </section>;
}
