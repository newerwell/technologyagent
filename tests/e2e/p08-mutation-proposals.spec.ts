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

test("approved generic business proposal executes from the shared orders page", async ({ page }) => {
  const sessionReady = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/session/me" && response.status() === 200;
  });
  await page.goto("/orders");
  await sessionReady;
  const payload = { action: "supplier_create", payload: { code: `E2E-EXEC-${Date.now()}`, name: "浏览器执行供应商" } };
  const proposal = await page.evaluate(async (body) => {
    const response = await fetch("/api/mutations/proposals", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    });
    return { ok: response.ok, body: await response.json() };
  }, payload);
  expect(proposal.ok).toBeTruthy();
  await page.reload();
  const card = page.locator("article.card").filter({ hasText: "supplier_create" }).filter({ hasText: payload.payload.code });
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "批准" }).click();
  await card.getByRole("button", { name: "执行已批准提案" }).click();
  await expect(card).toContainText("已执行并核对结果");
  await expect(card).toContainText("状态：consumed");
});

test("order amendment proposal displays server-computed old and new amounts", async ({ page }) => {
  const sessionReady = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/session/me" && response.status() === 200;
  });
  await page.goto("/orders");
  await sessionReady;
  const created = await page.evaluate(async () => {
    const ordersResponse = await fetch("/api/orders?page=1&page_size=100");
    const orders = (await ordersResponse.json()).data.records as Array<{ id: string; version: number; items: Array<{ part_id: string }> }>;
    const order = orders.find((candidate) => candidate.items.some((item) => item.part_id === "P001"));
    if (!order) throw new Error("seed order with P001 is required");
    const response = await fetch("/api/mutations/proposals", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ action: "order_update", payload: { order_id: order.id, expected_version: order.version,
        items: [{ part_id: "P001", quote_id: "Q01", quantity: 50 }] } }) });
    const body = await response.json();
    return { status: response.status, approvalId: body.data.approval_id as string,
      oldTotalCents: body.data.fact_snapshot.old.total_cents as number };
  });
  expect(created.status).toBe(200);
  expect(created.approvalId).toBeTruthy();
  expect(created.oldTotalCents).toBeGreaterThanOrEqual(0);
  await page.reload();
  const card = page.getByTestId(`proposal-card-${created.approvalId}`);
  await expect(card).toBeVisible();
  const facts = card.getByTestId("amendment-facts");
  await expect(facts).toBeVisible();
  await expect(facts).toContainText("P001");
  await expect(facts).toContainText("套");
  await expect(facts).toContainText(`原总额：${(created.oldTotalCents / 100).toFixed(2)} 元`);
  await expect(facts).toContainText("新总额：600.00 元");
});
