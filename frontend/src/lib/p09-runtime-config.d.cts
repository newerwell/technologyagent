export type P09RuntimeEnvironment = Record<string, string | undefined>;

export type P09BrowserRuntime = {
  ports: { API_PORT: string; FRONTEND_PORT: string; MCP_PORT: string };
  baseURL: string;
  restartEnv: P09RuntimeEnvironment;
};

export function resolveP09BrowserRuntime(environment: P09RuntimeEnvironment): P09BrowserRuntime;
export function assertP09BrowserIsolation(environment: P09RuntimeEnvironment): void;
