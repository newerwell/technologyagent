import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DataPage } from "./DataPage";
import { ReplenishmentPreview } from "./ReplenishmentPreview";
import type { Part } from "../../lib/domain-types";

type EnvelopeBody<T> = {
  ok: boolean;
  data: T;
  error: null;
  meta: {
    request_id: string;
    data_source: string;
    as_of: string;
    scope: string;
  };
};

function envelope<T>(data: T): EnvelopeBody<T> {
  return {
    ok: true,
    data,
    error: null,
    meta: {
      request_id: "test",
      data_source: "local_seed",
      as_of: "2026-10-23T02:00:00Z",
      scope: "shared_catalog",
    },
  };
}

function page<T>(records: T[], total: number, current: number, size: number) {
  return {
    records,
    total,
    page: current,
    page_size: size,
    pages: total === 0 ? 0 : Math.ceil(total / size),
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function inventoryRecord(id: string, warehouse: string) {
  return {
    id,
    part_id: id === "I001" ? "P001" : "P002",
    warehouse_id: warehouse,
    on_hand: 20,
    reserved: 5,
    inbound: 10,
    safety_stock: 30,
    target_stock: 80,
    version: 1,
    available: 15,
    projected: 25,
    shortage: 55,
    warning: true,
  };
}

const part: Part = {
  id: "P001",
  code: "BRK-001",
  name: "刹车片",
  specification: "前轮",
  unit: "套",
  category: "制动",
  active: true,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("DataPage", () => {
  it("resets inventory page to 1 when warehouse changes", async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        urls.push(path);
        if (path === "/api/session/me") {
          return jsonResponse(envelope({ owner_id: "local-owner", request_id: "r", mode: "local" }));
        }
        if (path.startsWith("/api/inventory/summary")) {
          return jsonResponse(
            envelope({
              warehouse_id: "W01",
              records: 5,
              warehouses: 2,
              total_on_hand: 50,
              total_reserved: 5,
              total_inbound: 10,
              total_available: 45,
              total_projected: 55,
              total_safety_stock: 50,
              total_target_stock: 100,
              total_shortage: 55,
              warning_count: 2,
            }),
          );
        }
        if (path.startsWith("/api/inventory/warnings")) {
          return jsonResponse(envelope(page([], 0, 1, 100)));
        }
        if (path.startsWith("/api/inventory?")) {
          const parsed = new URL(path, "http://127.0.0.1");
          const current = Number(parsed.searchParams.get("page") ?? "1");
          const warehouse = parsed.searchParams.get("warehouse_id");
          const total = warehouse === "W02" ? 1 : 5;
          const records =
            warehouse === "W02"
              ? [inventoryRecord("I002", "W02")]
              : current === 1
                ? [inventoryRecord("I001", "W01"), inventoryRecord("I002", "W01"), inventoryRecord("I003", "W01")]
                : [inventoryRecord("I004", "W01"), inventoryRecord("I005", "W01")];
          return jsonResponse(envelope(page(records, total, current, 3)));
        }
        if (path.startsWith("/api/parts")) {
          return jsonResponse(envelope(page([part], 1, 1, 100)));
        }
        if (path.startsWith("/api/suppliers")) {
          return jsonResponse(envelope(page([], 0, 1, 100)));
        }
        if (path.startsWith("/api/quotes")) {
          return jsonResponse(envelope(page([], 0, 1, 100)));
        }
        throw new Error("unexpected fetch: " + path);
      }),
    );

    render(<DataPage />);

    expect(await screen.findByText(/第 1 \/ 2 页/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    expect(await screen.findByText(/第 2 \/ 2 页/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("筛选仓库"), {
      target: { value: "W02" },
    });
    expect(await screen.findByText(/第 1 \/ 1 页/)).toBeInTheDocument();
    expect(
      urls.some((url) => url.includes("/api/inventory?") && url.includes("warehouse_id=W02") && url.includes("page=1")),
    ).toBe(true);
  });

  it("keeps catalog data and does not refetch parts when only inventory page changes", async () => {
    const partsUrls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (path === "/api/session/me") {
          return jsonResponse(envelope({ owner_id: "local-owner", request_id: "r", mode: "local" }));
        }
        if (path.startsWith("/api/inventory/summary")) {
          return jsonResponse(
            envelope({
              warehouse_id: "W01",
              records: 5,
              warehouses: 2,
              total_on_hand: 50,
              total_reserved: 5,
              total_inbound: 10,
              total_available: 45,
              total_projected: 55,
              total_safety_stock: 50,
              total_target_stock: 100,
              total_shortage: 55,
              warning_count: 2,
            }),
          );
        }
        if (path.startsWith("/api/inventory/warnings")) {
          return jsonResponse(envelope(page([], 0, 1, 100)));
        }
        if (path.startsWith("/api/inventory?")) {
          const parsed = new URL(path, "http://127.0.0.1");
          const current = Number(parsed.searchParams.get("page") ?? "1");
          return jsonResponse(
            envelope(page([inventoryRecord("I001", "W01")], 5, current, 3)),
          );
        }
        if (path.startsWith("/api/parts")) {
          partsUrls.push(path);
          return jsonResponse(envelope(page([part], 1, 1, 100)));
        }
        if (path.startsWith("/api/suppliers")) {
          return jsonResponse(envelope(page([], 0, 1, 100)));
        }
        if (path.startsWith("/api/quotes")) {
          return jsonResponse(envelope(page([], 0, 1, 100)));
        }
        throw new Error("unexpected fetch: " + path);
      }),
    );

    render(<DataPage />);
    expect(await screen.findByText(/第 1 \/ 2 页/)).toBeInTheDocument();
    expect(partsUrls.length).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    expect(await screen.findByText(/第 2 \/ 2 页/)).toBeInTheDocument();
    expect(partsUrls.length).toBe(1);
    expect(screen.getByLabelText("预览物料")).toHaveValue("P001");
  });

  it("retries the initial local session after a failure when refresh is clicked", async () => {
    const sessionUrls: string[] = [];
    let sessionCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (path === "/api/session/me") {
          sessionCalls += 1;
          sessionUrls.push(path);
          if (sessionCalls === 1) {
            throw new TypeError("network down");
          }
          return jsonResponse(envelope({ owner_id: "local-owner", request_id: "r", mode: "local" }));
        }
        if (path.startsWith("/api/inventory/summary")) {
          return jsonResponse(
            envelope({
              warehouse_id: "W01",
              records: 0,
              warehouses: 0,
              total_on_hand: 0,
              total_reserved: 0,
              total_inbound: 0,
              total_available: 0,
              total_projected: 0,
              total_safety_stock: 0,
              total_target_stock: 0,
              total_shortage: 0,
              warning_count: 0,
            }),
          );
        }
        if (path.startsWith("/api/inventory/warnings")) {
          return jsonResponse(envelope(page([], 0, 1, 100)));
        }
        if (path.startsWith("/api/inventory?")) {
          return jsonResponse(envelope(page([], 0, 1, 3)));
        }
        if (path.startsWith("/api/parts")) {
          return jsonResponse(envelope(page([], 0, 1, 100)));
        }
        if (path.startsWith("/api/suppliers")) {
          return jsonResponse(envelope(page([], 0, 1, 100)));
        }
        if (path.startsWith("/api/quotes")) {
          return jsonResponse(envelope(page([], 0, 1, 100)));
        }
        throw new Error("unexpected fetch: " + path);
      }),
    );

    render(<DataPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("无法连接后端服务");
    expect(screen.getByRole("button", { name: "刷新数据" })).not.toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "刷新数据" }));
    await waitFor(() => expect(sessionCalls).toBe(2));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(sessionUrls).toEqual(["/api/session/me", "/api/session/me"]);
  });

  it("recovers from a mid-session 401 with a bounded refresh", async () => {
    let partsCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (path === "/api/session/me") {
          return jsonResponse(envelope({ owner_id: "local-owner", request_id: "r", mode: "local" }));
        }
        if (path.startsWith("/api/parts")) {
          partsCalls += 1;
          if (partsCalls === 2) {
            return jsonResponse(
              {
                ok: false,
                data: null,
                error: { code: "UNAUTHENTICATED", message: "session expired", retryable: false },
                meta: envelope(null).meta,
              },
              401,
            );
          }
          return jsonResponse(envelope(page([part], 1, 1, 100)));
        }
        if (path.startsWith("/api/inventory/summary")) {
          return jsonResponse(
            envelope({
              warehouse_id: "W01", records: 1, warehouses: 1, total_on_hand: 20,
              total_reserved: 5, total_inbound: 10, total_available: 15,
              total_projected: 25, total_safety_stock: 30, total_target_stock: 80,
              total_shortage: 55, warning_count: 1,
            }),
          );
        }
        if (path.startsWith("/api/inventory/warnings")) {
          return jsonResponse(envelope(page([], 0, 1, 100)));
        }
        if (path.startsWith("/api/inventory?")) {
          return jsonResponse(envelope(page([inventoryRecord("I001", "W01")], 1, 1, 3)));
        }
        if (path.startsWith("/api/suppliers") || path.startsWith("/api/quotes")) {
          return jsonResponse(envelope(page([], 0, 1, 100)));
        }
        throw new Error("unexpected fetch: " + path);
      }),
    );

    render(<DataPage />);
    expect(await screen.findByText(/第 1 \/ 1 页/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "刷新数据" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("本地会话已失效");
    expect(screen.getByRole("button", { name: "刷新数据" })).not.toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "刷新数据" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(partsCalls).toBe(3);
  });
});

describe("ReplenishmentPreview", () => {
  it("clears a previous amount and shows the real API error", async () => {
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        calls += 1;
        if (calls === 1) {
          return jsonResponse(
            envelope({
              lines: [
                {
                  part_id: "P001",
                  part_name: "刹车片",
                  inventory_id: "I001",
                  warehouse_id: "W01",
                  unit: "套",
                  available: 15,
                  projected: 25,
                  shortage: 55,
                  warning: true,
                  candidate_quotes: [],
                  recommended_quote_id: "Q02",
                  quantity: 55,
                  total_cents: 60500,
                  actionable: true,
                  missing_fields: [],
                  inventory_version: 1,
                },
              ],
              snapshot_versions: { I001: 1 },
              source_refs: [],
            }),
          );
        }
        return jsonResponse(
          {
            ok: false,
            data: null,
            error: {
              code: "VALIDATION_ERROR",
              message: "page_size must be between 1 and 100",
              retryable: false,
            },
            meta: envelope(null).meta,
          },
          422,
        );
      }),
    );

    render(<ReplenishmentPreview parts={[part]} warehouseId="W01" catalogGeneration={0} />);
    const button = screen.getByRole("button", { name: "生成补货预览" });
    fireEvent.click(button);
    expect(await screen.findByTestId("preview-total")).toHaveTextContent("¥605.00");

    fireEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "page_size must be between 1 and 100",
    );
    await waitFor(() => expect(screen.queryByTestId("preview-total")).not.toBeInTheDocument());
  });
});