import { expect, test } from "../../frontend/node_modules/@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const screenshotDir = resolve(process.cwd(), "../evidence/screenshots");
mkdirSync(screenshotDir, { recursive: true });

test("P09 desktop 1440x900 chat and run history stay usable", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/chat");
  await expect(page.getByTestId("chat-input")).toBeVisible();
  await page.getByTestId("chat-input").fill("P001 在 W01 缺多少？ P09 桌面验收");
  await page.getByTestId("send-button").click();
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 25000 });
  await expect(page.getByTestId("tool-card")).toBeVisible();
  const noOverflow = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(noOverflow).toBe(true);
  await page.screenshot({ path: resolve(screenshotDir, "p09-desktop-1440x900.png"), fullPage: true });
});

test("P09 mobile 390x844 orders and chat controls have no page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/orders");
  await expect(page.getByRole("heading", { name: /订单/ }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "返回对话" })).toBeVisible();
  const warehouseInput = await page.getByLabel("仓库编号").boundingBox();
  expect(warehouseInput?.width ?? 0).toBeGreaterThan(240);
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport);
  expect(dimensions.body).toBeLessThanOrEqual(dimensions.viewport);
  await page.screenshot({ path: resolve(screenshotDir, "p09-mobile-390x844.png"), fullPage: true });
});
