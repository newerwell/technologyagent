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
  await sendMessage(page, "P001 在 W01 缺多少？ E2E 测试流式输出");
  await expect(page.getByTestId("tool-card")).toBeVisible({ timeout: 15000 });
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20000 });
  await expect(page.getByTestId("harness-phase")).toContainText("评审通过");
  await expect(page.getByTestId("plan-panel")).toBeVisible();
  await expect(page.getByTestId("review-panel")).toContainText("评审通过");
  await expect(page.locator("[data-message-id]")).toHaveCount(2, { timeout: 10000 });
  expect(page.url()).toContain("?thread=");
  const assistant = await page.getByTestId("message-list").innerText();
  expect(assistant).toContain("ScriptedModel");
  expect(assistant).not.toContain("undefined");

  await page.reload();
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20000 });
  await expect(page.getByTestId("harness-phase")).toContainText("评审通过");
  await expect(page.getByTestId("plan-panel")).toBeVisible();
  await expect(page.locator("[data-message-id]")).toHaveCount(2);
  await expect(page.getByTestId("tool-card")).toHaveCount(1);
  await expect(page.getByTestId("message-list")).not.toContainText("生成中");
  await expect(page.locator(".message-user")).toHaveCount(1);
  await expect(page.locator(".message-assistant")).toHaveCount(1);
});

test("reload during a run recovers from persisted events without duplicates", async ({ page }) => {
  await page.goto("/chat");
  await sendMessage(page, "P001 在 W01 缺多少？ E2E 中途刷新");
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

test("delayed conversation response cannot overwrite the selected thread", async ({ page }) => {
  await page.goto("/chat");
  await sendMessage(page, "E2E 慢会话 A");
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20000 });
  await expect(page.locator("[data-message-id]")).toHaveCount(2, { timeout: 10000 });
  const threadA = new URL(page.url()).searchParams.get("thread");
  expect(threadA).toBeTruthy();

  await page.getByTestId("new-chat-button").click();
  await sendMessage(page, "E2E 快会话 B");
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20000 });
  await expect(page.locator("[data-message-id]")).toHaveCount(2, { timeout: 10000 });
  const threadB = new URL(page.url()).searchParams.get("thread");
  expect(threadB).toBeTruthy();

  let releaseA: (() => void) | null = null;
  const held = new Promise<void>((resolve) => {
    void page.route("**/api/conversations/" + threadA, async (route) => {
      resolve();
      await new Promise<void>((release) => {
        releaseA = release;
      });
      await route.continue();
    });
  });
  await page.getByTestId("conversation-item").filter({ hasText: "E2E 慢会话 A" }).first().click();
  await held;
  await page.getByTestId("conversation-item").filter({ hasText: "E2E 快会话 B" }).first().click();
  await expect(page.getByTestId("message-list")).toContainText("E2E 快会话 B", { timeout: 10000 });
  releaseA?.();
  await page.waitForTimeout(500);
  expect(page.url()).toContain("thread=" + threadB);
  await expect(page.getByTestId("message-list")).toContainText("E2E 快会话 B");
  await expect(page.getByTestId("message-list")).not.toContainText("E2E 慢会话 A");
});

test("session precheck holds the send lock before any stream starts", async ({ page }) => {
  await page.goto("/chat");
  const streamRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/chat/stream")) streamRequests.push(request.url());
  });
  let releasePrecheck: (() => void) | null = null;
  const held = new Promise<void>((resolve) => {
    let once = true;
    void page.route("**/api/session/me", async (route) => {
      if (once) {
        once = false;
        resolve();
        await new Promise<void>((release) => {
          releasePrecheck = release;
        });
      }
      await route.continue();
    });
  });
  await page.getByTestId("chat-input").fill("E2E 唯一发送");
  await page.getByTestId("send-button").click();
  await held;
  await expect(page.getByTestId("send-button")).toBeDisabled();
  await page.getByTestId("chat-input").fill("E2E 不应发送");
  await expect(page.getByTestId("send-button")).toBeDisabled();
  releasePrecheck?.();
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20000 });
  expect(streamRequests).toHaveLength(1);
});

test("old same-view terminal refresh cannot replace a newer continuous run", async ({ page }) => {
  await page.goto("/chat");
  let oldRefreshStarted!: () => void;
  const held = new Promise<void>((resolve) => { oldRefreshStarted = resolve; });
  let releaseOld: (() => void) | null = null;
  let holdNextDetail = true;
  await page.route("**/api/conversations/*", async (route) => {
    if (holdNextDetail && route.request().method() === "GET") {
      holdNextDetail = false;
      oldRefreshStarted();
      await new Promise<void>((release) => { releaseOld = release; });
    }
    await route.continue();
  });

  await sendMessage(page, "E2E 第一轮完成");
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20000 });
  await held;
  await sendMessage(page, "E2E 同会话第二轮");
  await expect(page.locator(".chat-toolbar")).toContainText("status running", { timeout: 10000 });
  await expect(page.locator(".chat-toolbar")).toContainText("run_", { timeout: 10000 });
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20000 });
  releaseOld?.();
  await page.waitForTimeout(300);
  await expect(page.locator(".chat-toolbar")).toContainText("status completed");
  await expect(page.getByTestId("message-list")).toContainText("E2E 第一轮完成");
  await expect(page.getByTestId("message-list")).toContainText("E2E 同会话第二轮");
  await expect(page.locator("[data-message-id]")).toHaveCount(4);
});
