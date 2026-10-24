import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApprovalCard } from "../components/approval/ApprovalCard";
import type { OrderDraftView } from "../lib/api";

const draft: OrderDraftView = {
  id: "drf-1", owner_id: "owner-a", supplier_id: "S01", warehouse_id: "W01",
  items: [{ part_id: "P001", quantity: 55, unit_price_cents: 1200, quote_id: "Q01", line_total_cents: 66000 }],
  total_cents: 66000, version: 1, state: "pending_approval", source_refs: [], snapshot_versions: { I001: 1 },
};

describe("ApprovalCard", () => {
  it("shows server totals and keeps decision actions locked while submitting", () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const { container } = render(<ApprovalCard draft={draft} quantity={55} busy onQuantity={vi.fn()} onEdit={vi.fn()}
      onApprove={onApprove} onReject={onReject} />);

    expect(container.querySelector(".total")?.textContent).toContain("660.00 元");
    expect(screen.getByRole("button", { name: "批准并创建订单" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "拒绝" }));
    expect(onApprove).not.toHaveBeenCalled();
    expect(onReject).not.toHaveBeenCalled();
  });

  it("renders the edited server version and amount without recalculating it", () => {
    const { container } = render(<ApprovalCard draft={{ ...draft, version: 2, total_cents: 72000,
      items: [{ ...draft.items[0], quantity: 60, line_total_cents: 72000 }] }}
      quantity={60} busy={false} onQuantity={vi.fn()} onEdit={vi.fn()} onApprove={vi.fn()} onReject={vi.fn()} />);
    expect(screen.getByText("版本 2")).toBeTruthy();
    expect(container.querySelector(".total")?.textContent).toContain("720.00 元");
  });
});
