function resolvePort(name, value, fallback) {
  const candidate = typeof value === "string" && value.trim() ? value.trim() : fallback;
  if (!/^\d+$/.test(candidate)) throw new Error(`${name} must be a TCP port`);
  const port = Number(candidate);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${name} must be between 1 and 65535`);
  }
  return String(port);
}

function resolveP09BrowserRuntime(environment) {
  const ports = {
    API_PORT: resolvePort("API_PORT", environment.API_PORT, "8030"),
    FRONTEND_PORT: resolvePort("FRONTEND_PORT", environment.FRONTEND_PORT, "3030"),
    MCP_PORT: resolvePort("MCP_PORT", environment.MCP_PORT, "9030"),
  };
  if (new Set(Object.values(ports)).size !== 3) throw new Error("Service ports must be distinct");
  const requestedBaseURL = (typeof environment.P09_BROWSER_BASE_URL === "string"
    ? environment.P09_BROWSER_BASE_URL.trim() : "")
    || `http://127.0.0.1:${ports.FRONTEND_PORT}`;
  let parsed;
  try {
    parsed = new URL(requestedBaseURL);
  } catch {
    throw new Error("P09_BROWSER_BASE_URL must be an absolute HTTP URL");
  }
  if (parsed.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(parsed.hostname) || parsed.username || parsed.password) {
    throw new Error("P09_BROWSER_BASE_URL must be a loopback HTTP URL without credentials");
  }
  if (parsed.port !== ports.FRONTEND_PORT) {
    throw new Error("P09_BROWSER_BASE_URL port must match FRONTEND_PORT");
  }
  if (parsed.pathname !== "/" || parsed.search || parsed.hash) {
    throw new Error("P09_BROWSER_BASE_URL must identify the frontend origin only");
  }
  const baseURL = parsed.origin;
  return {
    ports,
    baseURL,
    restartEnv: {
      ...environment,
      ...ports,
      P09_BROWSER_BASE_URL: baseURL,
      LIVE_API_URL: `http://127.0.0.1:${ports.API_PORT}`,
    },
  };
}

function assertP09BrowserIsolation(environment) {
  const expectedMongo = "mongodb://127.0.0.1:27028/?replicaSet=ta-rs&directConnection=true";
  const failures = [];
  if (environment.COMPOSE_PROJECT_NAME !== "technologyagent-p09-acceptance") {
    failures.push("COMPOSE_PROJECT_NAME must be technologyagent-p09-acceptance");
  }
  if (!environment.COMPOSE_FILE?.replaceAll("\\", "/").endsWith("/compose.p09-acceptance.yaml")) {
    failures.push("COMPOSE_FILE must point to compose.p09-acceptance.yaml");
  }
  if (environment.MONGODB_URI !== expectedMongo || environment.MONGODB_TEST_URI !== expectedMongo) {
    failures.push("Mongo URIs must target the isolated 27028 ta-rs replica set");
  }
  const cleanDatabase = environment.P09_CLEAN_ACCEPTANCE === "1"
    && /^technologyagent_test_p09_(clean|restored)_[a-zA-Z0-9_]+$/.test(environment.MONGODB_DATABASE || "");
  if (environment.MONGODB_DATABASE !== "technologyagent_test_p09_browser" && !cleanDatabase) {
    failures.push("MONGODB_DATABASE must be technologyagent_test_p09_browser or an explicitly enabled P09 clean/restored test database");
  }
  for (const name of ["INVENTORY_DATA_SOURCE", "PARTS_DATA_SOURCE", "SUPPLIERS_DATA_SOURCE", "ORDERS_DATA_SOURCE"]) {
    if (environment[name] !== "local_seed") failures.push(`${name} must be local_seed`);
  }
  if (environment.INVENTORY_SNAPSHOT_PATH !== "") failures.push("INVENTORY_SNAPSHOT_PATH must be explicitly empty");
  if (environment.MODEL_MODE !== "fake" || environment.RUN_LIVE_MODEL !== "0") {
    failures.push("browser acceptance must use MODEL_MODE=fake and RUN_LIVE_MODEL=0");
  }
  if (failures.length > 0) throw new Error(`Unsafe P09 browser environment: ${failures.join("; ")}`);
}

module.exports = { resolveP09BrowserRuntime, assertP09BrowserIsolation };
