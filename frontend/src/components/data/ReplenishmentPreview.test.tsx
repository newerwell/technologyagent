import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReplenishmentPreview } from "./ReplenishmentPreview";
import type { Part } from "../../lib/domain-types";

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

function envelope<T>(data: T) {
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

function line(partId: string, totalCents: number, quoteId: string | null) {
  return {
    part_id: partId,
    part_name: partId,
    inventory_id: "I-" + partId,
    warehouse_id: "W01",
    unit: "套",
    available: 15,
    projected: 25,
    shortage: 55,
    warning: true,
    candidate_quotes: [],
    recommended_quote_id: quoteId,
    quantity: quoteId ? 55 : 0,
    total_cents: totalCents,
    actionable: quoteId !== null,
    missing_fields: quoteId ? [] : ["valid_quote"],
    inventory_version: 1,
  };
}

const parts: Part[] = [
  { id: "P001", code: "P001", name: "P001", unit: "套", specification: "", category: "", active: true },
  { id: "P002", code: "P002", name: "P002", unit: "个", specification: "", category: "", active: true },
  { id: "P003", code: "P003", name: "P003", unit: "个", specification: "", category: "", active: true },
];

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ReplenishmentPreview request generation", () => {
  it("explains that an inactive part cannot be purchased", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(envelope({
      lines: [{ ...line("P001", 0, null), actionable: false, missing_fields: ["part_inactive"] }],
      snapshot_versions: {}, source_refs: [],
    }))));

    render(<ReplenishmentPreview parts={parts} warehouseId="W01" catalogGeneration={0} />);
    fireEvent.click(screen.getByRole("button", { name: "生成补货预览" }));

    expect(await screen.findByText(/物料已停用/)).toBeInTheDocument();
  });

  it("ignores an old warehouse response after switching to a new warehouse", async () => {
    const oldRequest = deferred<Response>();
    const fetchMock = vi.fn(() => oldRequest.promise);
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = render(<ReplenishmentPreview parts={parts} warehouseId="W01" catalogGeneration={0} />);
    fireEvent.click(screen.getByRole("button", { name: "生成补货预览" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    rerender(<ReplenishmentPreview parts={parts} warehouseId="W02" catalogGeneration={0} />);
    await act(async () => {
      oldRequest.resolve(jsonResponse(envelope({ lines: [line("P001", 60500, "Q02")], snapshot_versions: {}, source_refs: [] })));
    });

    await waitFor(() => expect(screen.queryByTestId("preview-total")).not.toBeInTheDocument());
    expect(screen.queryByText("¥605.00")).not.toBeInTheDocument();
  });

  it("does not let old rejection/finally clear a new request", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        calls += 1;
        return calls === 1 ? first.promise : second.promise;
      }),
    );

    const { rerender } = render(<ReplenishmentPreview parts={parts} warehouseId="W01" catalogGeneration={0} />);
    fireEvent.click(screen.getByRole("button", { name: "生成补货预览" }));
    await waitFor(() => expect(calls).toBe(1));

    rerender(<ReplenishmentPreview parts={parts} warehouseId="W02" catalogGeneration={0} />);
    const button = await screen.findByRole("button", { name: "生成补货预览" });
    expect(button).not.toBeDisabled();
    fireEvent.click(button);
    await waitFor(() => expect(calls).toBe(2));

    await act(async () => {
      first.reject(new Error("old request failed"));
    });
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "计算中…" })).toBeDisabled();

    await act(async () => {
      second.resolve(jsonResponse(envelope({ lines: [line("P001", 70000, "Q01")], snapshot_versions: {}, source_refs: [] })));
    });
    expect(await screen.findByTestId("preview-total")).toHaveTextContent("¥700.00");
  });

  it("clears the old result when max lead changes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(envelope({ lines: [line("P001", 60500, "Q02")], snapshot_versions: {}, source_refs: [] })),
      ),
    );

    render(<ReplenishmentPreview parts={parts} warehouseId="W01" catalogGeneration={0} />);
    fireEvent.click(screen.getByRole("button", { name: "生成补货预览" }));
    expect(await screen.findByTestId("preview-total")).toHaveTextContent("¥605.00");

    fireEvent.change(screen.getByLabelText("最大交期"), { target: { value: "7" } });
    await waitFor(() => expect(screen.queryByTestId("preview-total")).not.toBeInTheDocument());
  });

  it("clears a P003 preview when the catalog removes P003 and selects a valid part", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(envelope({ lines: [line("P003", 0, null)], snapshot_versions: {}, source_refs: [] })),
      ),
    );

    const { rerender } = render(<ReplenishmentPreview parts={parts} warehouseId="W01" catalogGeneration={0} />);
    fireEvent.change(screen.getByLabelText("预览物料"), { target: { value: "P003" } });
    fireEvent.click(screen.getByRole("button", { name: "生成补货预览" }));
    expect(await screen.findByText("无可确认推荐")).toBeInTheDocument();
    expect(screen.getByTestId("preview-total")).toHaveTextContent("¥0.00");

    rerender(<ReplenishmentPreview parts={parts.filter((part) => part.id !== "P003")} warehouseId="W01" catalogGeneration={0} />);
    await waitFor(() => expect(screen.queryByTestId("preview-total")).not.toBeInTheDocument());
    expect(screen.getByLabelText("预览物料")).toHaveValue("P001");
  });

  it("clears the result when the catalog generation changes even if parts are unchanged", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(envelope({ lines: [line("P001", 60500, "Q02")], snapshot_versions: {}, source_refs: [] })),
      ),
    );

    const { rerender } = render(
      <ReplenishmentPreview parts={parts} warehouseId="W01" catalogGeneration={0} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "生成补货预览" }));
    expect(await screen.findByTestId("preview-total")).toHaveTextContent("¥605.00");

    rerender(<ReplenishmentPreview parts={parts} warehouseId="W01" catalogGeneration={1} />);
    await waitFor(() => expect(screen.queryByTestId("preview-total")).not.toBeInTheDocument());
  });
});
