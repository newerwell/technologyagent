import type {
  InventorySummary,
  InventoryView,
  Page,
  Part,
  PreviewResult,
  QuoteView,
  ReplenishmentRequest,
  Supplier,
} from "./domain-types";
import type {
  ChatRequest,
  ConversationView,
  EventEnvelope,
  RunView,
  ThreadView,
} from "./events";

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

export type OrderDraftView = {
  id: string;
  owner_id: string;
  supplier_id: string;
  warehouse_id: string;
  items: Array<{ part_id: string; quantity: number; unit_price_cents: number; quote_id: string; line_total_cents: number }>;
  total_cents: number;
  version: number;
  state: "draft" | "pending_approval" | "approved" | "rejected" | "superseded";
  source_refs: Array<{ entity: string; id: string; data_source: string; as_of: string }>;
  snapshot_versions: Record<string, number>;
};

export type PurchaseOrderView = {
  id: string;
  number: string;
  supplier_id: string;
  warehouse_id: string;
  items: OrderDraftView["items"];
  total_cents: number;
  status: string;
  created_at: string;
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

export async function ensureLocalSession(): Promise<WhoAmIData> {
  try {
    return (await getMe()).data as WhoAmIData;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      await createLocalSession();
      return (await getMe()).data as WhoAmIData;
    }
    throw error;
  }
}

function queryString(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? "?" + encoded : "";
}

export type PartQuery = {
  name?: string;
  part_id?: string;
  page?: number;
  page_size?: number;
};

export type SupplierQuery = {
  name?: string;
  supplier_id?: string;
  page?: number;
  page_size?: number;
};

export type QuoteQuery = {
  part_name?: string;
  part_id?: string;
  supplier_id?: string;
  page?: number;
  page_size?: number;
};

export type InventoryQuery = {
  warehouse_id?: string;
  part_name?: string;
  page?: number;
  page_size?: number;
};

export async function getParts(params: PartQuery = {}): Promise<Envelope<Page<Part>>> {
  return request<Page<Part>>("/api/parts" + queryString(params));
}

export async function getSuppliers(
  params: SupplierQuery = {},
): Promise<Envelope<Page<Supplier>>> {
  return request<Page<Supplier>>("/api/suppliers" + queryString(params));
}

export async function getQuotes(params: QuoteQuery = {}): Promise<Envelope<Page<QuoteView>>> {
  return request<Page<QuoteView>>("/api/quotes" + queryString(params));
}

export async function getInventory(
  params: InventoryQuery = {},
): Promise<Envelope<Page<InventoryView>>> {
  return request<Page<InventoryView>>("/api/inventory" + queryString(params));
}

export async function getInventoryWarnings(
  params: InventoryQuery = {},
): Promise<Envelope<Page<InventoryView>>> {
  return request<Page<InventoryView>>("/api/inventory/warnings" + queryString(params));
}

export async function getInventorySummary(
  params: { warehouse_id?: string } = {},
): Promise<Envelope<InventorySummary>> {
  return request<InventorySummary>("/api/inventory/summary" + queryString(params));
}

export async function previewReplenishment(
  body: ReplenishmentRequest,
): Promise<Envelope<PreviewResult>> {
  return request<PreviewResult>("/api/replenishment/preview", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function prepareDraft(body: {
  part_ids: string[]; warehouse_id?: string; supplier_id?: string;
  max_lead_days?: number; quantities?: Record<string, number>;
}): Promise<Envelope<{ drafts: OrderDraftView[]; missing_fields: string[] }>> {
  return request("/api/drafts", { method: "POST", body: JSON.stringify(body) });
}

export async function listDrafts(): Promise<Envelope<OrderDraftView[]>> {
  return request("/api/drafts");
}

export async function patchDraft(id: string, body: {
  expected_version: number; items: Array<{ part_id: string; quote_id: string; quantity: number }>; supplier_id?: string; warehouse_id?: string;
}): Promise<Envelope<OrderDraftView>> {
  return request(`/api/drafts/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) });
}

export async function requestApproval(id: string, runId: string): Promise<Envelope<{ approval_id: string; status: string }>> {
  return request(`/api/drafts/${encodeURIComponent(id)}/approval`, { method: "POST", body: JSON.stringify({ run_id: runId }) });
}

export async function resolveApproval(approvalId: string, body: {
  interrupt_id: string; decision: "approve" | "reject"; expected_version: number; idempotency_key: string;
}): Promise<Envelope<{ approval_id: string; status: string }>> {
  return request(`/api/approvals/${encodeURIComponent(approvalId)}/resolve`, { method: "POST", body: JSON.stringify(body) });
}

export async function createApprovedOrder(body: {
  draft_id: string; approval_id: string; idempotency_key: string;
}): Promise<Envelope<{ operation_id: string; status: string; order: PurchaseOrderView }>> {
  return request("/api/orders/create", { method: "POST", body: JSON.stringify(body) });
}

export type OperationReconciliation = {
  status: "succeeded" | "processing" | "outcome_unknown" | "retryable" | "failed";
  operation_id: string;
  result?: { operation_id: string; status: string; order: PurchaseOrderView };
  idempotency_key?: string;
  retry_after_seconds?: number;
  message?: string;
};

export async function reconcileOperation(operationId: string): Promise<Envelope<OperationReconciliation>> {
  return request(`/api/operations/${encodeURIComponent(operationId)}/reconcile`, { method: "POST" });
}

export async function listOrders(params: { page?: number; page_size?: number } = {}): Promise<Envelope<Page<PurchaseOrderView>>> {
  return request("/api/orders" + queryString(params));
}

export async function listConversations(): Promise<Envelope<ThreadView[]>> {
  return request<ThreadView[]>("/api/conversations");
}

export async function getConversation(threadId: string): Promise<Envelope<ConversationView>> {
  return request<ConversationView>("/api/conversations/" + encodeURIComponent(threadId));
}

export async function deleteConversation(threadId: string): Promise<Envelope<{ deleted: boolean }>> {
  return request<{ deleted: boolean }>("/api/conversations/" + encodeURIComponent(threadId), {
    method: "DELETE",
  });
}

export async function getRun(runId: string): Promise<Envelope<RunView>> {
  return request<RunView>("/api/runs/" + encodeURIComponent(runId));
}

export async function resumeOrderRun(runId: string, body: {
  interrupt_id: string; decision: "approve" | "reject" | "supplement" | "edit";
  expected_version: number | null; payload?: Record<string, unknown>; idempotency_key: string;
}): Promise<Envelope<RunView>> {
  return request(`/api/runs/${encodeURIComponent(runId)}/resume`, { method: "POST", body: JSON.stringify(body) });
}

export async function startOrderWorkflow(body: {
  message: string; request_id: string; thread_id?: string;
  draft: { part_ids: string[]; warehouse_id?: string; max_lead_days?: number; quantities?: Record<string, number> };
}): Promise<Envelope<RunView>> {
  return request("/api/order-workflows", { method: "POST", body: JSON.stringify(body) }, 30000);
}

export async function getDraft(id: string): Promise<Envelope<OrderDraftView>> {
  return request(`/api/drafts/${encodeURIComponent(id)}`);
}

export async function getRunEvents(
  runId: string,
  afterSeq = 0,
): Promise<Envelope<EventEnvelope[]>> {
  return request<EventEnvelope[]>(
    "/api/runs/" + encodeURIComponent(runId) + "/events?after_seq=" + afterSeq,
  );
}

export async function cancelRun(runId: string): Promise<Envelope<RunView>> {
  return request<RunView>("/api/runs/" + encodeURIComponent(runId) + "/cancel", {
    method: "POST",
  });
}

export async function startChatStream(
  body: ChatRequest,
  init: RequestInit = {},
): Promise<Response> {
  const response = await fetch("/api/chat/stream", {
    ...init,
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json", ...(init.headers ?? {}) },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let payload: Envelope<unknown> | null = null;
    try {
      payload = (await response.json()) as Envelope<unknown>;
    } catch {
      // fall through with status-only error
    }
    const failure = payload?.error;
    throw new ApiError(
      failure?.code ?? "HTTP_ERROR",
      failure?.message ?? "聊天请求失败（HTTP " + response.status + "）",
      response.status,
      failure?.retryable ?? false,
      payload,
    );
  }
  return response;
}
