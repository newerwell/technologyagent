import type { ReviewResult } from "../../lib/events";

export function ReviewPanel({ review }: { review: ReviewResult | null }) {
  if (!review) return null;
  return <section className="card workflow-panel" aria-label="结果评审" data-testid="review-panel">
    <h2>{review.passed ? "评审通过" : "评审未通过"}</h2>
    <p>检查 {review.checks?.filter((item) => item.passed).length ?? 0}/{review.checks?.length ?? 0} 项通过 · 修订 {review.revision_count ?? 0}/2</p>
    <ul>{review.checks?.map((check, index) => <li key={`${check.check_id}-${index}`}>
      <strong>{check.check_id}</strong>：{check.passed ? "通过" : "未通过"}{check.reason ? ` — ${check.reason}` : ""}
      {check.evidence_refs?.length ? <small>依据：{check.evidence_refs.join("、")}</small> : null}
    </li>)}</ul>
    {review.incomplete_items?.length ? <p>未完成项：{review.incomplete_items.join("、")}</p> : null}
  </section>;
}
