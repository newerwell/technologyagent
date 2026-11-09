import { defineConfig, devices } from "@playwright/test";
import { resolveP09BrowserRuntime } from "./src/lib/p09-runtime-config.cjs";

const runtime = resolveP09BrowserRuntime(process.env);
export default defineConfig({
  testDir: "../tests/acceptance",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: { baseURL: runtime.baseURL, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], channel: "chrome" } }],
});
