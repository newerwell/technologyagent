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
  artifacts: Array<{ _id: string; owner_id: string; run_id: string; storage_key: string; sha256: string }>;
  business: { orders: number; successful_operations: number; inventory: { inbound: number; on_hand: number; version: number } };
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
  app("start.ps1", targetEnv);
  await page.reload();
  const approvalCard = page.getByTestId("approval-card")
    .filter({ hasText: pending.draft_id.slice(-8) }).filter({ hasText: "版本 2" });
  await expect(approvalCard).toHaveCount(1);
  await expect(approvalCard).toContainText("720.00 元");
  expect(await getPendingWorkflow(page, threadId)).toEqual(pending);
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
    downloads.push({ ...artifact, restored_sha256: sha256, association });
  }
  const finalFacts = capture(targetDatabase, targetStorage, targetEnv);
  expect(finalFacts.business.orders).toBe(3);
  expect(finalFacts.business.successful_operations).toBe(1);
  expect(finalFacts.business.inventory).toMatchObject({ inbound: 70, on_hand: 20 });
  expect(finalFacts.artifacts).toEqual(sourceFacts.artifacts);
  await saveR8Screenshot(page, "clean-restore", "approved-once-after-full-restore", reports.artifacts);
  const evidenceRoot = resolve(repoRoot, ".runtime/reports/clean-restore");
  mkdirSync(evidenceRoot, { recursive: true });
  const factsPath = resolve(evidenceRoot, suffix + "-facts.json");
  writeFileSync(factsPath, JSON.stringify({ source_database: sourceDatabase, target_database: targetDatabase,
    source_storage: sourceStorage, target_storage: targetStorage, backup: backupPath, pending,
    source_before_backup: sourceFacts, restored_before_startup: restoredBeforeStartup, final: finalFacts,
    order: added[0], artifacts: downloads, runtime: { ports: runtime.ports, baseURL: runtime.baseURL } }, null, 2));
  console.log("P09_CLEAN_RESTORE", JSON.stringify({ source_database: sourceDatabase,
    target_database: targetDatabase, collection_count: Object.keys(sourceFacts.collections).length,
    restored_order_id: added[0].id, facts_path: factsPath }));
});
