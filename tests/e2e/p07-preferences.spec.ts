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
