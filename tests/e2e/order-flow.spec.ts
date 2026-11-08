// Browser MVP workflow against the isolated Mongo-backed API in fake mode.
// Every viewport executes actual report generation/download and the full
// quote-backed order approval flow. No success route is mocked.
import { expect, test, type Page } from "../../frontend/node_modules/@playwright/test";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  assertP09BrowserIsolation,
  resolveP09BrowserRuntime,
} from "../../frontend/src/lib/p09-runtime-config.cjs";

const currentDirectory = process.cwd();
const repoRoot = resolve(currentDirectory,
  currentDirectory.split(/[\\/]/).pop()?.toLowerCase() === "frontend" ? ".." : ".");
const downloadRoot = resolve(repoRoot, ".runtime/reports/p09-r8-downloads");
const screenshotRoot = resolve(repoRoot, "evidence/screenshots");
const screenshotBatch = process.env.P09_EVIDENCE_BATCH?.trim()
  || new Date().toISOString().replace(/[:.]/g, "-");
mkdirSync(downloadRoot, { recursive: true });

for (const viewport of [{ name: "desktop-1440x900", width: 1440, height: 900 },
                        { name: "mobile-390x844", width: 390, height: 844 }]) {
  test(`P09 ${viewport.name}: report download, editable draft, restart recovery and idempotent approval`, async ({ page }) => {
    test.setTimeout(360_000);
    const runtime = resolveP09BrowserRuntime(process.env);
    const restartEnv = runtime.restartEnv;
    assertP09BrowserIsolation(restartEnv);
    // Re-establish the documented synthetic fixture for each viewport. The
    // seed command itself refuses reset outside technologyagent_test_* and
    // deliberately leaves runs/events/artifacts intact as acceptance history.
    execFileSync(resolve(repoRoot, ".venv/Scripts/python.exe"), ["-m", "scripts.seed", "--reset"], {
      cwd: repoRoot, stdio: "inherit", windowsHide: true, timeout: 60_000, env: restartEnv,
    });
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const { threadId, artifacts } = await generateAndOpenReports(page, viewport.name);
    expect(new URL(page.url()).origin).toBe(runtime.baseURL);
    await saveR8Screenshot(page, viewport.name, "reports-downloaded", artifacts);
    const inventoryBefore = await getP001Inventory(page);
    expect(inventoryBefore.inbound).toBe(10);
    const { before, threadId: orderThreadId } = await beginAndEditOrder(page);
    const pending = await getPendingWorkflow(page, orderThreadId);

    // Restart only the project-managed processes while retaining the current
    // isolated compose/database/source/model environment from this process.
    const stop = resolve(repoRoot, "stop.ps1");
    const start = resolve(repoRoot, "start.ps1");
    execFileSync("pwsh.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", stop], {
      cwd: repoRoot, stdio: "inherit", windowsHide: true, timeout: 60_000,
      env: restartEnv,
    });
    execFileSync("pwsh.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", start], {
      cwd: repoRoot, stdio: "inherit", windowsHide: true, timeout: 180_000,
      env: restartEnv,
    });

    await page.reload();
    const approvalCard = () => page.getByTestId("approval-card")
      .filter({ hasText: pending.draft_id.slice(-8) })
      .filter({ hasText: "版本 2" }).filter({ hasText: "720.00 元" });
    await expect(approvalCard()).toHaveCount(1);
    await expect(approvalCard()).toContainText("版本 2");
    await expect(approvalCard()).toContainText("720.00 元");
    await saveR8Screenshot(page, viewport.name, "approval-restored", artifacts);
    await approvalCard().getByRole("button", { name: "批准并创建订单" }).click();
    await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20_000 });

    // Repeat the exact durable decision key after the browser action. The
    // workflow must reconcile to the same terminal result, not submit again.
    const replay = await page.request.post(`/api/runs/${encodeURIComponent(pending.run_id)}/resume`, {
      data: {
        interrupt_id: pending.interrupt_id,
        decision: "approve",
        expected_version: pending.version,
        payload: {},
        idempotency_key: `approve_${pending.run_id}_${pending.draft_version}`,
      },
    });
    expect(replay.ok()).toBeTruthy();
    const replayRun = (await replay.json()).data;
    expect(replayRun.status).toBe("completed");

    const finalOrdersResponse = await page.request.get("/api/orders?page=1&page_size=100");
    expect(finalOrdersResponse.ok()).toBeTruthy();
    const finalOrders = (await finalOrdersResponse.json()).data.records as Array<{
      id: string; number: string; warehouse_id: string; total_cents: number;
      items: Array<{ part_id: string; quantity: number }>;
    }>;
    expect(finalOrders).toHaveLength(before.count + 1);
    const added = finalOrders.filter((row) => !before.ids.has(row.id));
    expect(added).toHaveLength(1);
    expect(added[0].warehouse_id).toBe("W01");
    expect(added[0].total_cents).toBe(72_000);
    expect(added[0].items).toContainEqual(expect.objectContaining({ part_id: "P001", quantity: 60 }));
    const inventoryAfter = await getP001Inventory(page);
    expect(inventoryAfter.inbound).toBe(70);
    await page.goto("/orders");
    await expect(page.getByTestId("order-row")).toHaveCount(before.count + 1);
    const createdOrderRow = page.getByTestId("order-row").filter({ hasText: added[0].number });
    await expect(createdOrderRow).toHaveCount(1);
    await expect(createdOrderRow).toContainText("720.00 元");
    await saveR8Screenshot(page, viewport.name, "order-approved", artifacts);

    const eventsResponse = await page.request.get(`/api/runs/${encodeURIComponent(pending.run_id)}/events`);
    expect(eventsResponse.ok()).toBeTruthy();
    const events = (await eventsResponse.json()).data as Array<{ type: string; payload: Record<string, unknown> }>;
    const review = events.find((event) => event.type === "review" && event.payload.passed === true);
    expect(review).toBeTruthy();
    const checks = review!.payload.details as Array<{ check_id: string; passed: boolean; evidence_refs: string[] }>;
    const orderCheck = checks.find((check) => check.check_id === "ORDER_EXISTS");
    expect(orderCheck?.passed).toBe(true);
    expect(orderCheck?.evidence_refs).toHaveLength(1);
    const operationId = orderCheck!.evidence_refs[0];
    const reconciled = await page.request.post(`/api/operations/${encodeURIComponent(operationId)}/reconcile`);
    expect(reconciled.ok()).toBeTruthy();
    const operation = (await reconciled.json()).data;
    expect(operation.status).toBe("succeeded");
    expect(operation.result.order.id).toBe(added[0].id);

    await page.goto(`/chat?thread=${encodeURIComponent(pending.thread_id)}`);
    await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20_000 });
    console.log("P09_R8_ORDER_FACTS", JSON.stringify({ viewport: viewport.name, before_count: before.count,
      created_order_id: added[0].id, order_number: added[0].number, quantity: added[0].items[0].quantity,
      total_cents: added[0].total_cents, inbound_before: inventoryBefore.inbound,
      inbound_after: inventoryAfter.inbound, successful_operation_id: operationId,
      duplicate_decision_status: replayRun.status, report_thread_id: threadId }));
  });
}

type R8ArtifactEvidence = { format: string; artifact_id: string; run_id: string; filename: string; sha256: string };

async function generateAndOpenReports(page: Page, viewport: string): Promise<{ threadId: string; artifacts: R8ArtifactEvidence[] }> {
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
      run_id: artifact!.run_id, filename: artifact!.filename, sha256 });
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

async function saveR8Screenshot(
  page: Page,
  viewport: string,
  phase: string,
  artifacts: R8ArtifactEvidence[],
): Promise<void> {
  mkdirSync(screenshotRoot, { recursive: true });
  const path = resolve(screenshotRoot, `P09-R8-${screenshotBatch}-${viewport}-${phase}.png`);
  await page.screenshot({ path, fullPage: true });
  const sha256 = createHash("sha256").update(readFileSync(path)).digest("hex");
  console.log("P09_R8_SCREENSHOT", JSON.stringify({ viewport, phase, path, sha256,
    artifact_ids: artifacts.map((artifact) => artifact.artifact_id),
    run_ids: artifacts.map((artifact) => artifact.run_id),
    artifact_files: artifacts.map((artifact) => ({ filename: artifact.filename, sha256: artifact.sha256 })) }));
}

async function getP001Inventory(page: Page): Promise<{ inbound: number; on_hand: number; reserved: number }> {
  const response = await page.request.get("/api/inventory?warehouse_id=W01&page=1&page_size=100");
  expect(response.ok()).toBeTruthy();
  const data = (await response.json()).data as { records: Array<{ part_id: string; inbound: number; on_hand: number; reserved: number }> };
  const row = data.records.find((item) => item.part_id === "P001");
  expect(row).toBeTruthy();
  return { inbound: row!.inbound, on_hand: row!.on_hand, reserved: row!.reserved };
}

async function beginAndEditOrder(page: Page): Promise<{ before: { count: number; ids: Set<string> }; threadId: string }> {
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

async function getPendingWorkflow(page: Page, threadId: string): Promise<{
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
