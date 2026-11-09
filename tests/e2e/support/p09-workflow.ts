// Shared real-browser actions; all business rules remain in backend services.
import { expect, type Page } from "../../../frontend/node_modules/@playwright/test";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
const currentDirectory = process.cwd();
export const repoRoot = resolve(currentDirectory,
  currentDirectory.split(/[\\/]/).pop()?.toLowerCase() === "frontend" ? ".." : ".");
export const downloadRoot = resolve(repoRoot, ".runtime/reports/p09-r8-downloads");
const screenshotRoot = resolve(repoRoot, "evidence/screenshots");
export const screenshotBatch = process.env.P09_EVIDENCE_BATCH?.trim() || new Date().toISOString().replace(/[:.]/g, "-");
export const screenshotsByViewport = new Map<string, Array<Record<string, unknown>>>();
mkdirSync(downloadRoot, { recursive: true });

export type R8ArtifactEvidence = { format: string; artifact_id: string; run_id: string; filename: string; sha256: string;
  size_bytes: number; source_refs: Array<Record<string, string>>; downloaded_path: string };

export async function generateAndOpenReports(page: Page, viewport: string): Promise<{ threadId: string; artifacts: R8ArtifactEvidence[] }> {
  const reports: Array<{ format: "md" | "csv" | "json"; mime: string }> = [
    { format: "md", mime: "text/markdown" },
    { format: "csv", mime: "text/csv" },
    { format: "json", mime: "application/json" },
  ];
  let firstThreadId = "";
  const evidence: R8ArtifactEvidence[] = [];
  for (const report of reports) {
    await page.goto("/chat");
    const prompt = `查询 W01 仓库库存并生成${report.format.toUpperCase()}报告`;
    await page.getByTestId("chat-input").fill(prompt);
    await page.getByTestId("send-button").click();
    await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 35_000 });
    const threadId = new URL(page.url()).searchParams.get("thread");
    expect(threadId).toBeTruthy();
    firstThreadId ||= threadId!;
    await expect(page.getByTestId("artifact-card")).toHaveCount(1, { timeout: 10_000 });

    const listedResponse = await page.request.get(`/api/artifacts?thread_id=${encodeURIComponent(threadId!)}`);
    expect(listedResponse.ok()).toBeTruthy();
    const artifacts = (await listedResponse.json()).data as Array<{
      artifact_id: string; run_id: string; filename: string; mime: string; size_bytes: number;
      source_refs: Array<Record<string, string>>; download_url: string;
    }>;
    const artifact = artifacts.find((item) => item.filename.toLowerCase().endsWith(`.${report.format}`));
    expect(artifact, `registered ${report.format} artifact`).toBeTruthy();
    expect(artifact!.mime).toBe(report.mime);
    expect(artifact!.size_bytes).toBeGreaterThan(0);
    expect(artifact!.source_refs.length).toBeGreaterThan(0);
    expect(artifact!.source_refs.every((source) => source.data_source === "local_seed")).toBeTruthy();
    const conversationResponse = await page.request.get(`/api/conversations/${encodeURIComponent(threadId!)}`);
    expect(conversationResponse.ok()).toBeTruthy();
    const conversation = (await conversationResponse.json()).data;
    expect(conversation.latest_run.id).toBe(artifact!.run_id);
    expect(conversation.latest_run.status).toBe("completed");
    const eventsResponse = await page.request.get(`/api/runs/${encodeURIComponent(artifact!.run_id)}/events`);
    expect(eventsResponse.ok()).toBeTruthy();
    const events = (await eventsResponse.json()).data as Array<{ type: string; payload: Record<string, unknown> }>;
    const verified = events.find((event) => event.type === "report_verified"
      && event.payload.artifact_id === artifact!.artifact_id);
    expect(verified, "formal report body and scope verification event").toBeTruthy();
    expect(verified!.payload.scope).toBe("shared_catalog");

    const card = page.getByTestId("artifact-card").filter({ hasText: artifact!.filename });
    await card.getByRole("link", { name: "下载文件" }).click();
    // Retrieve the same authorized download URL through this browser context
    // (which carries the local owner cookie); this preserves the real API
    // response/body even on Chrome builds that suppress the Download event.
    const downloadUrl = new URL(artifact!.download_url, page.url()).toString();
    const downloadResponse = await page.request.get(downloadUrl);
    expect(downloadResponse.status()).toBe(200);
    const disposition = downloadResponse.headers()["content-disposition"] ?? "";
    expect(decodeURIComponent(disposition)).toContain(artifact!.filename);
    const filePath = resolve(downloadRoot, `${viewport}-${report.format}-${artifact!.artifact_id}.${report.format}`);
    writeFileSync(filePath, await downloadResponse.body());
    const bytes = readFileSync(filePath);
    expect(bytes.byteLength).toBe(artifact!.size_bytes);
    const sha256 = createHash("sha256").update(bytes).digest("hex");
    evidence.push({ format: report.format, artifact_id: artifact!.artifact_id,
      run_id: artifact!.run_id, filename: artifact!.filename, sha256, size_bytes: bytes.byteLength,
      source_refs: artifact!.source_refs, downloaded_path: filePath });
    const body = bytes.toString("utf8");
    expect(body).toContain("P001");
    expect(body).toContain("W01");

    if (report.format === "json") {
      const parsed = JSON.parse(body) as { rows: unknown[][] };
      expect(parsed.rows.some((row) => row[0] === "P001" && row[1] === "W01")).toBeTruthy();
      expect(parsed.rows.every((row) => row[1] === "W01")).toBeTruthy();
    } else if (report.format === "csv") {
      const detailRows = body.split(/\r?\n/).filter((line) => /^P\d{3},/.test(line));
      expect(detailRows.some((line) => line.startsWith("P001,W01,"))).toBeTruthy();
      expect(detailRows.every((line) => /^P\d{3},W01,/.test(line))).toBeTruthy();
    } else {
      const detailRows = body.split(/\r?\n/).filter((line) => /^\| P\d{3} \|/.test(line));
      expect(detailRows.some((line) => line.includes("| P001 | W01 |"))).toBeTruthy();
      expect(detailRows.every((line) => line.includes("| W01 |"))).toBeTruthy();
    }
    console.log("P09_R8_ARTIFACT", JSON.stringify({ viewport, format: report.format,
      artifact_id: artifact!.artifact_id, run_id: artifact!.run_id, filename: artifact!.filename,
      bytes: bytes.byteLength, sha256, scope: verified!.payload.scope,
      source_refs: artifact!.source_refs, actual_download_http: downloadResponse.status(),
      downloaded_to_file: filePath }));
  }
  return { threadId: firstThreadId, artifacts: evidence };
}

export async function saveR8Screenshot(
  page: Page,
  viewport: string,
  phase: string,
  artifacts: R8ArtifactEvidence[],
): Promise<void> {
  mkdirSync(screenshotRoot, { recursive: true });
  const path = resolve(screenshotRoot, `P09-R8-${screenshotBatch}-${viewport}-${phase}.png`);
  await page.screenshot({ path, fullPage: true });
  const sha256 = createHash("sha256").update(readFileSync(path)).digest("hex");
  const previous = screenshotsByViewport.get(viewport) ?? [];
  screenshotsByViewport.set(viewport, [...previous, { phase, path, sha256,
    artifact_files: artifacts.map((artifact) => ({ filename: artifact.filename, sha256: artifact.sha256 })) }]);
  console.log("P09_R8_SCREENSHOT", JSON.stringify({ viewport, phase, path, sha256,
    artifact_ids: artifacts.map((artifact) => artifact.artifact_id),
    run_ids: artifacts.map((artifact) => artifact.run_id),
    artifact_files: artifacts.map((artifact) => ({ filename: artifact.filename, sha256: artifact.sha256 })) }));
}

export async function getP001Inventory(page: Page): Promise<{ inbound: number; on_hand: number; reserved: number }> {
  const response = await page.request.get("/api/inventory?warehouse_id=W01&page=1&page_size=100");
  expect(response.ok()).toBeTruthy();
  const data = (await response.json()).data as { records: Array<{ part_id: string; inbound: number; on_hand: number; reserved: number }> };
  const row = data.records.find((item) => item.part_id === "P001");
  expect(row).toBeTruthy();
  return { inbound: row!.inbound, on_hand: row!.on_hand, reserved: row!.reserved };
}

export async function beginAndEditOrder(page: Page): Promise<{ before: { count: number; ids: Set<string> }; threadId: string }> {
  await page.goto("/orders");
  const baselineResponse = await page.request.get("/api/orders?page=1&page_size=100");
  expect(baselineResponse.ok()).toBeTruthy();
  const baseline = (await baselineResponse.json()).data.records as Array<{ id: string }>;
  const before = { count: baseline.length, ids: new Set(baseline.map((row) => row.id)) };
  const preference = await page.request.delete("/api/preferences/default_warehouse");
  expect(preference.ok()).toBeTruthy();
  await page.getByRole("button", { name: "开始订单流程" }).click();
  await page.waitForURL(/\/chat\?thread=/);
  const threadId = new URL(page.url()).searchParams.get("thread");
  expect(threadId).toBeTruthy();
  await expect(page.getByTestId("workflow-supplement")).toBeVisible();
  await page.getByLabel("仓库编号").fill("W01");
  await page.getByRole("button", { name: "继续" }).click();
  const approvalCard = page.getByTestId("approval-card");
  await expect(approvalCard).toBeVisible();
  await expect(approvalCard).toContainText("660.00 元");
  await page.getByLabel("采购数量").fill("60");
  await page.getByRole("button", { name: "保存修改并重新确认" }).click();
  await expect(approvalCard).toContainText("版本 2");
  await expect(approvalCard).toContainText("720.00 元");
  await page.reload();
  await expect(page.getByTestId("approval-card")).toContainText("版本 2");
  await expect(page.getByTestId("approval-card")).toContainText("720.00 元");
  return { before, threadId: threadId! };
}

export async function getPendingWorkflow(page: Page, threadId: string): Promise<{
  draft_id: string; run_id: string; thread_id: string; interrupt_id: string; version: number; draft_version: number;
}> {
  const draftsResponse = await page.request.get("/api/drafts");
  expect(draftsResponse.ok()).toBeTruthy();
  const drafts = (await draftsResponse.json()).data as Array<{
    id: string; version: number; state: string; workflow?: { run_id: string; thread_id: string;
      pending_interrupt?: null | { kind: string; interrupt_id: string; version: number } };
  }>;
  const draft = drafts.find((item) => item.state === "pending_approval"
    && item.workflow?.thread_id === threadId
    && item.workflow?.pending_interrupt?.kind === "approval");
  expect(draft?.workflow).toBeTruthy();
  const interrupt = draft!.workflow!.pending_interrupt!;
  return { draft_id: draft!.id, run_id: draft!.workflow!.run_id, thread_id: draft!.workflow!.thread_id,
    interrupt_id: interrupt.interrupt_id, version: interrupt.version, draft_version: draft!.version };
}
