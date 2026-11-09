import { describe, expect, it } from "vitest";
import {
  assertP09BrowserIsolation,
  resolveP09BrowserRuntime,
} from "./p09-runtime-config.cjs";

const safeEnvironment = {
  COMPOSE_FILE: "C:/repo/compose.p09-acceptance.yaml",
  COMPOSE_PROJECT_NAME: "technologyagent-p09-acceptance",
  MONGODB_URI: "mongodb://127.0.0.1:27028/?replicaSet=ta-rs&directConnection=true",
  MONGODB_TEST_URI: "mongodb://127.0.0.1:27028/?replicaSet=ta-rs&directConnection=true",
  MONGODB_DATABASE: "technologyagent_test_p09_browser",
  INVENTORY_DATA_SOURCE: "local_seed",
  PARTS_DATA_SOURCE: "local_seed",
  SUPPLIERS_DATA_SOURCE: "local_seed",
  ORDERS_DATA_SOURCE: "local_seed",
  INVENTORY_SNAPSHOT_PATH: "",
  MODEL_MODE: "fake",
  RUN_LIVE_MODEL: "0",
};

describe("P09 browser runtime configuration", () => {
  it("uses documented default ports and a matching browser base URL", () => {
    const runtime = resolveP09BrowserRuntime(safeEnvironment);
    expect(runtime.ports).toEqual({ API_PORT: "8030", FRONTEND_PORT: "3030", MCP_PORT: "9030" });
    expect(runtime.baseURL).toBe("http://127.0.0.1:3030");
    expect(runtime.restartEnv.P09_BROWSER_BASE_URL).toBe(runtime.baseURL);
  });

  it("preserves dedicated ports for the browser URL and restarted services", () => {
    const runtime = resolveP09BrowserRuntime({
      ...safeEnvironment,
      API_PORT: "8131",
      FRONTEND_PORT: "3131",
      MCP_PORT: "9131",
    });
    expect(runtime.ports).toEqual({ API_PORT: "8131", FRONTEND_PORT: "3131", MCP_PORT: "9131" });
    expect(runtime.baseURL).toBe("http://127.0.0.1:3131");
    expect(runtime.restartEnv.API_PORT).toBe("8131");
    expect(runtime.restartEnv.FRONTEND_PORT).toBe("3131");
    expect(runtime.restartEnv.MCP_PORT).toBe("9131");
  });

  it("rejects a base URL that points at a different frontend port", () => {
    expect(() => resolveP09BrowserRuntime({
      ...safeEnvironment,
      FRONTEND_PORT: "3131",
      P09_BROWSER_BASE_URL: "http://127.0.0.1:3030",
    })).toThrow(/must match FRONTEND_PORT/);
  });

  it("requires the isolated fake browser database before any reset or restart", () => {
    expect(() => assertP09BrowserIsolation({
      ...safeEnvironment,
      MONGODB_DATABASE: "technologyagent_dev",
    })).toThrow(/technologyagent_test_p09_browser/);
    expect(() => assertP09BrowserIsolation(safeEnvironment)).not.toThrow();
  });

  it("preserves an explicitly isolated clean database and storage across restarts", () => {
    const environment = { ...safeEnvironment, P09_CLEAN_ACCEPTANCE: "1",
      MONGODB_DATABASE: "technologyagent_test_p09_clean_20261108_123456",
      STORAGE_ROOT: "C:/repo/.runtime/clean-storage", API_PORT: "8131", FRONTEND_PORT: "3131", MCP_PORT: "9131" };
    const runtime = resolveP09BrowserRuntime(environment);
    expect(() => assertP09BrowserIsolation(runtime.restartEnv)).not.toThrow();
    expect(runtime.restartEnv.MONGODB_DATABASE).toBe(environment.MONGODB_DATABASE);
    expect(runtime.restartEnv.STORAGE_ROOT).toBe(environment.STORAGE_ROOT);
    expect(runtime.restartEnv.LIVE_API_URL).toBe("http://127.0.0.1:8131");
    expect(() => assertP09BrowserIsolation({ ...environment, P09_CLEAN_ACCEPTANCE: "0" })).toThrow();
    expect(() => assertP09BrowserIsolation({ ...environment, MONGODB_DATABASE: "technologyagent_dev" })).toThrow();
  });

  it("rejects non-loopback origins and overlapping service ports", () => {
    expect(() => resolveP09BrowserRuntime({ ...safeEnvironment, P09_BROWSER_BASE_URL: "http://example.com:3030" })).toThrow();
    expect(() => resolveP09BrowserRuntime({ ...safeEnvironment, API_PORT: "3030" })).toThrow();
  });
});
