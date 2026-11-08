import { defineConfig, devices } from "@playwright/test";
import { resolveP09BrowserRuntime } from "./src/lib/p09-runtime-config.cjs";

const p09Runtime = resolveP09BrowserRuntime(process.env);

export default defineConfig({
  testDir: "../tests/e2e",
  fullyParallel: true,
  reporter: "list",
  use: {
    baseURL: p09Runtime.baseURL,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
  ],
});
