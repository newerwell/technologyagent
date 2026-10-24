// Browser MVP workflow against the Mongo-backed API in fake or explicitly enabled live mode.
import { expect, test } from "../../frontend/node_modules/@playwright/test";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

test("missing warehouse, editable quote-backed draft, persistent approval and refresh", async ({ page }) => {
  if (process.env.P04_RESTART_BACKEND === "1") test.setTimeout(240_000);
  const initialOrders = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/orders" && url.searchParams.get("page_size") === "100";
  });
  await page.goto("/orders");
  const orderRows = page.getByTestId("order-row");
  const baseline = await initialOrders;
  expect(baseline.ok()).toBe(true);
  const before = (await baseline.json()).data.total as number;
  await expect(orderRows).toHaveCount(Math.min(before, 100));
  await page.getByRole("button", { name: "开始订单流程" }).click();
  await page.waitForURL(/\/chat\?thread=/);
  if (process.env.P04_EXPECT_LIVE === "1") {
    await expect(page.getByTestId("fake-badge")).toContainText("Live Model · model_mode=live");
  }
  await expect(page.getByTestId("workflow-supplement")).toBeVisible();
  await page.getByLabel("仓库编号").fill("W01");
  await page.getByRole("button", { name: "继续" }).click();
  await expect(page.getByTestId("approval-card")).toBeVisible();
  await expect(page.getByTestId("approval-card")).toContainText("660.00 元");
  await page.getByLabel("采购数量").fill("60");
  await page.getByRole("button", { name: "保存修改并重新确认" }).click();
  await expect(page.getByTestId("approval-card")).toContainText("版本 2");
  await expect(page.getByTestId("approval-card")).toContainText("720.00 元");
  if (process.env.P04_RESTART_BACKEND === "1") {
    const repoRoot = existsSync(resolve(process.cwd(), "start.ps1"))
      ? process.cwd()
      : resolve(process.cwd(), "..");
    execFileSync("pwsh.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", resolve(repoRoot, "stop.ps1")], {
      cwd: repoRoot, stdio: "inherit", windowsHide: true, timeout: 60_000,
    });
    execFileSync("pwsh.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", resolve(repoRoot, "start.ps1")], {
      cwd: repoRoot, stdio: "inherit", windowsHide: true, timeout: 180_000,
      env: { ...process.env, MONGODB_DATABASE: "technologyagent_test_p04_browser" },
    });
  }
  await page.reload();
  await expect(page.getByTestId("approval-card")).toContainText("版本 2");
  await page.getByRole("button", { name: "批准并创建订单" }).click();
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 15000 });
  await page.getByRole("link", { name: "订单审批" }).click();
  await expect(page.getByTestId("order-row")).toHaveCount(before + 1, { timeout: 15000 });
  const createdOrder = page.getByTestId("order-row").filter({ hasText: "720.00 元" });
  await expect(createdOrder).toHaveCount(1);
  await expect(createdOrder).toContainText("S01");
  await expect(createdOrder).toContainText("W01");
});
