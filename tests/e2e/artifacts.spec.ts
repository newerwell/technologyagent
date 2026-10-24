import { expect, test } from "../../frontend/node_modules/@playwright/test";

const threadId = "thr_p06_artifact";
const runId = "run_p06_artifact";
const artifactId = "art_0123456789abcdef0123456789abcdef";

function envelope(data: unknown) {
  return { ok: true, data, error: null, meta: {
    request_id: "p06-browser", data_source: "fixture", as_of: "2026-10-24T00:00:00Z", scope: "local-owner",
  } };
}

test("persisted artifact event renders scoped report download and chart preview", async ({ page }) => {
  await page.route("**/api/session/me", (route) => route.fulfill({ json: envelope({ owner_id: "local-owner", request_id: "p06", mode: "local" }) }));
  await page.route("**/api/conversations", (route) => route.fulfill({ json: envelope([]) }));
  await page.route(`**/api/conversations/${threadId}`, (route) => route.fulfill({ json: envelope({
    thread: { id: threadId, title: "P06 产物", active_run_id: null, created_at: "2026-10-24T00:00:00Z", updated_at: "2026-10-24T00:00:00Z" },
    messages: [],
    latest_run: { id: runId, thread_id: threadId, status: "completed", phase: "result", task_type: "analysis",
      plan: [], evidence_refs: [], revision_count: 0, last_seq: 1, cancel_requested: false, available_actions: [],
      summary: "有效报价 Q01/Q02；P001、W01、55件；66000分 / 60500分", committed_facts: false,
      created_at: "2026-10-24T00:00:00Z", updated_at: "2026-10-24T00:00:00Z", finished_at: "2026-10-24T00:00:01Z", pending_interrupt: null },
  }) }));
  await page.route(`**/api/runs/${runId}/events*`, (route) => route.fulfill({ json: envelope([{
    schema_version: 1, type: "artifact_ready", event_id: "evt-p06-artifact", seq: 1, thread_id: threadId, run_id: runId,
    at: "2026-10-24T00:00:01Z", payload: { artifact_id: artifactId, filename: "报价比较.png", kind: "png", mime: "image/png",
      source_refs: [{ entity: "quote", id: "Q01" }, { entity: "quote", id: "Q02" }] },
  }]) }));

  await page.goto(`/chat?thread=${threadId}`);
  const card = page.getByTestId("artifact-card");
  await expect(card).toContainText("报价比较.png");
  await expect(card).toContainText("quote:Q01");
  await expect(card.getByRole("link", { name: "下载文件" })).toHaveAttribute("href", `/api/artifacts/${artifactId}`);
  await expect(card.getByRole("img", { name: "报价比较.png图表" })).toHaveAttribute("src", `/api/artifacts/${artifactId}/preview`);
});
