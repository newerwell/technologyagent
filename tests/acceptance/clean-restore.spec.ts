// Full restore acceptance is deliberately separate from the normal browser suite.
import { expect, test } from "../../frontend/node_modules/@playwright/test";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { assertP09BrowserIsolation, resolveP09BrowserRuntime } from "../../frontend/src/lib/p09-runtime-config.cjs";
import { repoRoot, generateAndOpenReports, beginAndEditOrder, getPendingWorkflow,
  getP001Inventory, saveR8Screenshot } from "../e2e/support/p09-workflow";

type RestoreFacts = {
  collections: Record<string, { count: number; sha256: string }>;
  artifacts: Array<{ _id: string; owner_id: string; run_id: string; storage_key: string; sha256: string; source_refs: unknown[] }>;
  business: { orders: number; successful_operations: number; inventory: { inbound: number; on_hand: number; version: number };
    approvals: Array<{ _id: string; status: string; decision: string; order_id?: string; draft_id: string; draft_version: number }>;
    order_operation_links: Array<{ _id: string; operation_id?: string }>;
    successful_operation_links: Array<{ _id: string; action: string; order_id: string }> };
};

test("clean checkout restores the full pending workflow and real artifacts before one approval", async ({ page }) => {
  test.setTimeout(600_000);
  const runtime = resolveP09BrowserRuntime(process.env);
  const sourceEnv = runtime.restartEnv;
  assertP09BrowserIsolation(sourceEnv);
  if (sourceEnv.P09_CLEAN_ACCEPTANCE !== "1" ||
      !/^technologyagent_test_p09_clean_[a-zA-Z0-9_]+$/.test(sourceEnv.MONGODB_DATABASE || "") ||
      !sourceEnv.STORAGE_ROOT) {
    throw new Error("Set P09_CLEAN_ACCEPTANCE=1, a unique clean test database and explicit isolated STORAGE_ROOT");
  }
  const sourceDatabase = sourceEnv.MONGODB_DATABASE!;
  const sourceStorage = resolve(sourceEnv.STORAGE_ROOT);
  const suffix = sourceDatabase.slice("technologyagent_test_p09_clean_".length);
  const targetDatabase = "technologyagent_test_p09_restored_" + suffix;
  const targetStorage = resolve(repoRoot, ".runtime/clean-restored-storage-" + suffix);
  const backupPath = resolve(repoRoot, ".runtime/clean-full-backup-" + suffix);
  if (existsSync(targetStorage) || existsSync(backupPath)) throw new Error("Clean restore requires unused target paths");
  const python = resolve(repoRoot, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
  const shell = process.platform === "win32" ? "pwsh.exe" : "pwsh";
  const run = (name: string, args: string[], environment = sourceEnv) => {
    execFileSync(shell, ["-NoProfile", "-File", resolve(repoRoot, "scripts", name), ...args],
      { cwd: repoRoot, env: environment, stdio: "inherit", windowsHide: true, timeout: 240_000 });
  };
  const app = (name: string, environment = sourceEnv) => {
    execFileSync(shell, ["-NoProfile", "-File", resolve(repoRoot, name)],
      { cwd: repoRoot, env: environment, stdio: "inherit", windowsHide: true, timeout: 240_000 });
  };
  const capture = (database: string, storage: string, environment = sourceEnv): RestoreFacts => {
    const text = execFileSync(python, ["-m", "scripts.p09_restore_facts", "--database", database,
      "--storage-root", storage], { cwd: repoRoot, env: environment, encoding: "utf8", windowsHide: true, timeout: 30_000 });
    return JSON.parse(text);
  };
  const mongoTarget = ["-MongoContainer", "technologyagent-p09-acceptance-mongodb", "-MongoPort", "27028"];
  execFileSync(python, ["-m", "scripts.seed", "--reset"],
    { cwd: repoRoot, env: sourceEnv, stdio: "inherit", windowsHide: true, timeout: 60_000 });
  await page.setViewportSize({ width: 1440, height: 900 });
  const reports = await generateAndOpenReports(page, "clean-before-restore");
  const { before, threadId } = await beginAndEditOrder(page);
  const pending = await getPendingWorkflow(page, threadId);
  expect(pending.draft_version).toBe(2);
  await saveR8Screenshot(page, "clean-restore", "pending-before-backup", reports.artifacts);
  app("stop.ps1");
  const sourceFacts = capture(sourceDatabase, sourceStorage);
  expect(sourceFacts.business.orders).toBe(2);
  expect(sourceFacts.business.successful_operations).toBe(0);
  expect(sourceFacts.business.inventory.inbound).toBe(10);
  // Fingerprints include every document of every collection, including
  // checkpoint blobs, sessions, versions, approvals and operation state.
  run("backup.ps1", ["-DatabaseName", sourceDatabase, "-Destination", backupPath,
    "-StorageRoot", sourceStorage, "-MaintenanceConfirmed", ...mongoTarget]);
  run("restore.ps1", ["-BackupDirectory", backupPath, "-TargetDatabase", targetDatabase,
    "-TargetStorageDirectory", targetStorage, "-MaintenanceConfirmed", ...mongoTarget]);
  const targetEnv = { ...sourceEnv, MONGODB_DATABASE: targetDatabase, STORAGE_ROOT: targetStorage };
  assertP09BrowserIsolation(targetEnv);
  const restoredBeforeStartup = capture(targetDatabase, targetStorage, targetEnv);
  expect(restoredBeforeStartup).toEqual(sourceFacts);
  expect(capture(sourceDatabase, sourceStorage)).toEqual(sourceFacts);
  app("start.ps1", targetEnv);
  await page.reload();
  const approvalCard = page.getByTestId("approval-card")
    .filter({ hasText: pending.draft_id.slice(-8) }).filter({ hasText: "版本 2" });
  await expect(approvalCard).toHaveCount(1);
  await expect(approvalCard).toContainText("720.00 元");
  expect(await getPendingWorkflow(page, threadId)).toEqual(pending);
  // Inject a separate trusted server-side test identity into its newly issued
  // session; public APIs continue to ignore caller-provided owner IDs.
  // Session tokens remain in the browser cookie jar and never enter CLI args,
  // evidence, logs or source fixtures.
  const other = await page.context().browser()!.newContext({ baseURL: runtime.baseURL });
  try {
    const created = await other.request.post(runtime.baseURL + "/api/session/local");
    expect(created.ok()).toBeTruthy();
    const identity = (await created.json()).data;
    const injectIdentity = [
      "import json,sys",
      "from datetime import datetime",
      "from pymongo import MongoClient",
      "from backend.app.config import load_settings",
      "from scripts.p09_restore_facts import validate_target",
      "s=load_settings(); validate_target(s.mongodb_database,s.mongodb_uri.get_secret_value())",
      "i=json.loads(sys.stdin.read())",
      "q={'owner_id':'local-owner','created_at':datetime.fromisoformat(i['created_at']),'expires_at':datetime.fromisoformat(i['expires_at'])}",
      "c=MongoClient(s.mongodb_uri.get_secret_value()); d=c[s.mongodb_database]",
      "assert d.sessions.count_documents(q)==1",
      "assert d.sessions.update_one(q,{'$set':{'owner_id':'p09-clean-other-owner'}}).modified_count==1",
      "c.close()",
    ].join("\n");
    execFileSync(python, ["-c", injectIdentity], { cwd: repoRoot, env: targetEnv,
      input: JSON.stringify({ created_at: identity.created_at, expires_at: identity.expires_at }),
      windowsHide: true, timeout: 30_000 });
    const who = await other.request.get(runtime.baseURL + "/api/session/me");
    expect(who.ok()).toBeTruthy();
    expect((await who.json()).data.owner_id).toBe("p09-clean-other-owner");
    for (const artifact of reports.artifacts) {
      const denied = await other.request.get(runtime.baseURL + "/api/artifacts/" + encodeURIComponent(artifact.artifact_id));
      expect(denied.status()).toBe(404);
    }
  } finally {
    await other.close();
  }
  await saveR8Screenshot(page, "clean-restore", "pending-after-full-restore", reports.artifacts);
  await approvalCard.getByRole("button", { name: "批准并创建订单" }).click();
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 25_000 });
  const replay = await page.request.post("/api/runs/" + encodeURIComponent(pending.run_id) + "/resume", {
    data: { interrupt_id: pending.interrupt_id, decision: "approve", expected_version: pending.version,
      payload: {}, idempotency_key: "approve_" + pending.run_id + "_" + pending.draft_version },
  });
  expect(replay.ok()).toBeTruthy();
  expect((await replay.json()).data.status).toBe("completed");
  const ordersResponse = await page.request.get("/api/orders?page=1&page_size=100");
  expect(ordersResponse.ok()).toBeTruthy();
  const orders = (await ordersResponse.json()).data.records;
  expect(orders).toHaveLength(before.count + 1);
  const added = orders.filter((order: { id: string }) => !before.ids.has(order.id));
  expect(added).toHaveLength(1);
  expect(added[0].total_cents).toBe(72000);
  expect(added[0].items).toContainEqual(expect.objectContaining({ part_id: "P001", quantity: 60 }));
  expect(await getP001Inventory(page)).toMatchObject({ inbound: 70, on_hand: 20 });
  const downloads = [];
  for (const artifact of reports.artifacts) {
    const response = await page.request.get("/api/artifacts/" + encodeURIComponent(artifact.artifact_id));
    expect(response.status()).toBe(200);
    const bytes = await response.body();
    expect(bytes.byteLength).toBe(artifact.size_bytes);
    const sha256 = createHash("sha256").update(bytes).digest("hex");
    expect(sha256).toBe(artifact.sha256);
    const association = restoredBeforeStartup.artifacts.find((item) => item._id === artifact.artifact_id);
    expect(association?.run_id).toBe(artifact.run_id);
    expect(association?.owner_id).toBeTruthy();
    expect(association?.sha256).toBe(sha256);
    expect(association?.source_refs).toEqual(artifact.source_refs);
    downloads.push({ ...artifact, restored_sha256: sha256, association });
  }
  const finalFacts = capture(targetDatabase, targetStorage, targetEnv);
  expect(finalFacts.business.orders).toBe(3);
  expect(finalFacts.business.successful_operations).toBe(1);
  const approvals = finalFacts.business.approvals.filter((item) => item._id === pending.interrupt_id);
  expect(approvals).toHaveLength(1);
  expect(approvals[0]).toMatchObject({ status: "consumed", decision: "approve",
    order_id: added[0].id, draft_id: pending.draft_id, draft_version: pending.draft_version });
  expect(finalFacts.business.successful_operation_links).toHaveLength(1);
  const operation = finalFacts.business.successful_operation_links[0];
  expect(operation).toMatchObject({ action: "order_create", order_id: added[0].id });
  expect(finalFacts.business.order_operation_links.find((item) => item._id === added[0].id)?.operation_id).toBe(operation._id);
  expect(finalFacts.business.inventory).toMatchObject({ inbound: 70, on_hand: 20 });
  expect(finalFacts.artifacts).toEqual(sourceFacts.artifacts);
  const sourceAfterApproval = capture(sourceDatabase, sourceStorage);
  expect(sourceAfterApproval.business.orders).toBe(2);
  expect(sourceAfterApproval.business.successful_operations).toBe(0);
  expect(sourceAfterApproval.artifacts).toEqual(sourceFacts.artifacts);
  await page.goto("/orders");
  await expect(page.getByTestId("order-row").filter({ hasText: added[0].number })).toHaveCount(1);
  await expect(page.getByTestId("order-row").filter({ hasText: added[0].number })).toContainText("720.00 元");
  await page.goto("/chat?thread=" + encodeURIComponent(threadId));
  await expect(page.locator(".chat-toolbar")).toContainText("status completed");
  await expect(page.getByTestId("message-list")).toContainText(added[0].number);
  await saveR8Screenshot(page, "clean-restore", "approved-once-after-full-restore", reports.artifacts);
  const evidenceRoot = resolve(repoRoot, ".runtime/reports/clean-restore");
  mkdirSync(evidenceRoot, { recursive: true });
  const factsPath = resolve(evidenceRoot, suffix + "-facts.json");
  writeFileSync(factsPath, JSON.stringify({ source_database: sourceDatabase, target_database: targetDatabase,
    source_storage: sourceStorage, target_storage: targetStorage, backup: backupPath, pending,
    source_before_backup: sourceFacts, restored_before_startup: restoredBeforeStartup, final: finalFacts,
    source_after_approval: sourceAfterApproval, wrong_owner_downloads_rejected: reports.artifacts.length,
    order: added[0], artifacts: downloads, runtime: { ports: runtime.ports, baseURL: runtime.baseURL } }, null, 2));
  console.log("P09_CLEAN_RESTORE", JSON.stringify({ source_database: sourceDatabase,
    target_database: targetDatabase, collection_count: Object.keys(sourceFacts.collections).length,
    restored_order_id: added[0].id, facts_path: factsPath }));
});
