import { expect, test } from "../../frontend/node_modules/@playwright/test";

test("generic business proposal is visible and human rejection has no business write", async ({ page }) => {
  const sessionReady = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/session/me" && response.status() === 200;
  });
  await page.goto("/orders");
  await sessionReady;
  const payload = { action: "supplier_create", payload: { code: `E2E-${Date.now()}`, name: "浏览器待审供应商" } };
  const proposal = await page.evaluate(async (body) => {
    const response = await fetch("/api/mutations/proposals", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    });
    return { ok: response.ok, body: await response.json() };
  }, payload);
  expect(proposal.ok).toBeTruthy();
  expect(proposal.body.data.payload.code).toBe(payload.payload.code);
  await page.reload();
  const card = page.locator("article.card").filter({ hasText: "supplier_create" }).filter({ hasText: payload.payload.code });
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "拒绝" }).click();
  await expect(card).toContainText("提案已拒绝");
});
