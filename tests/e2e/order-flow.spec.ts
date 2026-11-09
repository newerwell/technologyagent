// Browser MVP workflow against the isolated Mongo-backed API in fake mode.
// Every viewport executes actual report generation/download and the full
// quote-backed order approval flow. No success route is mocked.
import { expect, test } from "../../frontend/node_modules/@playwright/test";
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  assertP09BrowserIsolation,
  resolveP09BrowserRuntime,
} from "../../frontend/src/lib/p09-runtime-config.cjs";

import { repoRoot, downloadRoot, screenshotBatch, screenshotsByViewport, generateAndOpenReports,
  saveR8Screenshot, getP001Inventory, beginAndEditOrder, getPendingWorkflow } from "./support/p09-workflow";

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
    expect(inventoryBefore.on_hand).toBe(20);
    expect(inventoryAfter.on_hand).toBe(20);
    writeFileSync(resolve(downloadRoot, `${screenshotBatch}-${viewport.name}-facts.json`), JSON.stringify({
      viewport, runtime: { ports: runtime.ports, baseURL: runtime.baseURL,
        database: restartEnv.MONGODB_DATABASE, storage_root: restartEnv.STORAGE_ROOT,
        model_mode: restartEnv.MODEL_MODE, data_source: restartEnv.INVENTORY_DATA_SOURCE },
      pending, before_order_count: before.count, order: added[0], operation_id: operationId,
      inventory_before: inventoryBefore, inventory_after: inventoryAfter,
      duplicate_decision_status: replayRun.status, artifacts,
      screenshots: screenshotsByViewport.get(viewport.name) ?? [],
    }, null, 2));
  });
}
