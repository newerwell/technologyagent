// The E2E directory is at repository root; Playwright is installed with the frontend workspace.
import { expect, test } from "../../frontend/node_modules/@playwright/test";

test.describe.configure({ mode: "serial" });

async function sendMessage(page: import("../../frontend/node_modules/@playwright/test").Page, text: string) {
  await page.getByTestId("chat-input").fill(text);
  await page.getByTestId("send-button").click();
}

test("send, tool card, refresh and history keep one message", async ({ page }) => {
  await page.goto("/chat");
  await expect(page.getByTestId("fake-badge")).toBeVisible();
  await sendMessage(page, "E2E 测试流式输出");
  await expect(page.getByTestId("tool-card")).toBeVisible({ timeout: 15000 });
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20000 });
  await expect(page.locator("[data-message-id]")).toHaveCount(2, { timeout: 10000 });
  expect(page.url()).toContain("?thread=");
  const assistant = await page.getByTestId("message-list").innerText();
  expect(assistant).toContain("FakeAgent");
  expect(assistant).not.toContain("undefined");

  await page.reload();
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20000 });
  await expect(page.locator("[data-message-id]")).toHaveCount(2);
  await expect(page.getByTestId("tool-card")).toHaveCount(1);
  await expect(page.getByTestId("message-list")).not.toContainText("生成中");
  await expect(page.locator(".message-user")).toHaveCount(1);
  await expect(page.locator(".message-assistant")).toHaveCount(1);
});

test("reload during a run recovers from persisted events without duplicates", async ({ page }) => {
  await page.goto("/chat");
  await sendMessage(page, "E2E 中途刷新");
  await expect(page.locator(".chat-toolbar")).toContainText("status running", { timeout: 10000 });
  await page.waitForURL(/\?thread=/, { timeout: 10000 });
  await page.reload();
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20000 });
  await expect(page.locator("[data-message-id]")).toHaveCount(2, { timeout: 10000 });
  await expect(page.getByTestId("tool-card")).toHaveCount(1);
  await expect(page.locator(".message-user")).toHaveCount(1);
  await expect(page.locator(".message-assistant")).toHaveCount(1);
});

test("stop requests cancellation and leaves a queryable terminal run", async ({ page }) => {
  await page.goto("/chat");
  await sendMessage(page, "E2E 停止任务");
  await expect(page.getByTestId("stop-button")).toBeVisible({ timeout: 10000 });
  await page.getByTestId("stop-button").click();
  await expect(page.locator(".chat-toolbar")).toContainText("status cancelled", { timeout: 20000 });
  await expect(page.locator("[data-message-id]")).toHaveCount(2, { timeout: 10000 });
  await expect(page.getByTestId("message-list")).not.toContainText("生成中");
});

test("switch conversation reloads its history", async ({ page }) => {
  await page.goto("/chat");
  await sendMessage(page, "E2E 会话切换");
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20000 });
  await expect(page.locator("[data-message-id]")).toHaveCount(2, { timeout: 10000 });
  await page.getByTestId("new-chat-button").click();
  await sendMessage(page, "E2E 新会话");
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20000 });
  await page.getByTestId("conversation-item").filter({ hasText: "E2E 会话切换" }).first().click();
  await expect(page.getByTestId("message-list")).toContainText("E2E 会话切换", { timeout: 10000 });
  await expect(page.getByTestId("message-list")).not.toContainText("E2E 新会话");
});