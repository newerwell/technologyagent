import { expect, test } from "../../frontend/node_modules/@playwright/test";

test("explicit preferences can be remembered, restored, and removed", async ({ page }) => {
  await page.goto("/preferences");
  await expect(page.getByRole("heading", { name: "明确偏好" })).toBeVisible();
  const warehouse = page.getByLabel("默认仓库");
  await expect(warehouse).toBeEnabled();
  await warehouse.fill("W01");
  await page.getByRole("button", { name: "记住" }).first().click();
  await expect(page.getByText("已记住：W01")).toBeVisible();
  await page.reload();
  await expect(page.getByText("已记住：W01")).toBeVisible();
  await page.getByRole("button", { name: "删除" }).first().click();
  await expect(page.getByText("尚未记住").first()).toBeVisible();
});


test("chat remember survives a new conversation and scopes the next inventory call", async ({ page }) => {
  await page.goto("/chat");
  await page.getByTestId("chat-input").fill("记住默认仓库W02");
  await page.getByTestId("send-button").click();
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20000 });
  await expect(page.getByTestId("message-list")).toContainText("已按你的明确要求保存偏好");

  await page.getByTestId("new-chat-button").click();
  await page.getByTestId("chat-input").fill("P001库存缺口是多少？");
  await page.getByTestId("send-button").click();
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20000 });
  await expect(page.getByTestId("tool-card")).toContainText("W02");
  await expect(page.getByTestId("message-list")).toContainText("local_seed");

  await page.getByTestId("new-chat-button").click();
  await page.getByTestId("chat-input").fill("本轮在W01查询P001库存缺口");
  await page.getByTestId("send-button").click();
  await expect(page.locator(".chat-toolbar")).toContainText("status completed", { timeout: 20000 });
  await expect(page.getByTestId("tool-card")).toContainText("W01");
});
