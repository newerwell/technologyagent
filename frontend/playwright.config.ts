import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "../tests/e2e",
  fullyParallel: true,
  reporter: "list",
  use: {
    baseURL: process.env.P09_BROWSER_BASE_URL ?? "http://127.0.0.1:3030",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
  ],
});
