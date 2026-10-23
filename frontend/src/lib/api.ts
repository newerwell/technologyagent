export type ApiErrorBody = {
  code: string;
  message: string;
  retryable: boolean;
};

export type Meta = {
  request_id: string;
  data_source: string;
  as_of: string;
  scope: string;
};

export type Envelope<T> = {
  ok: boolean;
  data: T | null;
  error: ApiErrorBody | null;
  meta: Meta;
};

export type HealthData = {
  status: string;
  app: string;
  component: string;
};

export type CheckState = {
  status: string;
  detail?: string;
  reason?: string;
  latency_ms?: number;
};

export type ReadyData = {
  status: string;
  checks: Record<string, CheckState>;
};

export type SessionData = {
  owner_id: string;
  mode: string;
  created_at: string;
  expires_at: string;
  expires_in_seconds: number;
  cookie_name: string;
};

export type WhoAmIData = {
  owner_id: string;
  request_id: string;
  mode: string;
};

export class ApiError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly status: number;
  readonly payload: Envelope<unknown> | null;

  constructor(
    code: string,
    message: string,
    status: number,
    retryable = false,
    payload: Envelope<unknown> | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.retryable = retryable;
    this.payload = payload;
  }
}

const DEFAULT_TIMEOUT_MS = 8000;

async function request<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<Envelope<T>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const headers = new Headers(init.headers);
    if (init.body && !headers.has("content-type")) {
      headers.set("content-type", "application/json");
    }
    const response = await fetch(path, {
      ...init,
      headers,
      credentials: "include",
      signal: controller.signal,
    });
    let payload: Envelope<T>;
    try {
      payload = (await response.json()) as Envelope<T>;
    } catch {
      throw new ApiError(
        "INVALID_RESPONSE",
        `后端返回了非 JSON 响应（HTTP ${response.status}）`,
        response.status,
      );
    }
    if (!response.ok || !payload.ok) {
      throw new ApiError(
        payload.error?.code ?? "HTTP_ERROR",
        payload.error?.message ?? `请求失败（HTTP ${response.status}）`,
        response.status,
        payload.error?.retryable ?? false,
        payload as Envelope<unknown>,
      );
    }
    return payload;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("TIMEOUT", "请求超时，请检查后端是否已启动", 0, true);
    }
    throw new ApiError(
      "NETWORK_ERROR",
      "无法连接后端服务，请检查 start.ps1 和端口配置",
      0,
      true,
    );
  } finally {
    clearTimeout(timer);
  }
}

export async function getHealth(): Promise<Envelope<HealthData>> {
  return request<HealthData>("/health");
}

export async function getReady(): Promise<Envelope<ReadyData>> {
  return request<ReadyData>("/ready");
}

export async function createLocalSession(): Promise<Envelope<SessionData>> {
  return request<SessionData>("/api/session/local", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function getMe(): Promise<Envelope<WhoAmIData>> {
  return request<WhoAmIData>("/api/session/me");
}
