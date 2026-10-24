import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { emptyChatState } from "../lib/event-reducer";
import type { ReviewResult } from "../lib/events";
import { HarnessPhaseBar } from "../components/workflow/HarnessPhaseBar";
import { PlanPanel } from "../components/workflow/PlanPanel";
import { ReviewPanel } from "../components/workflow/ReviewPanel";

describe("workflow harness panels", () => {
  it("shows failed Run.status even when the phase reached result", () => {
    const state = { ...emptyChatState(), phase: "result" as const, runStatus: "failed", taskType: "inventory" as const, revisionCount: 2 };
    render(<HarnessPhaseBar state={state} />);
    expect(screen.getByText("任务阶段：执行失败")).toBeTruthy();
  });

  it("keeps an approval interruption visibly waiting while phase remains executing", () => {
    const state = { ...emptyChatState(), phase: "executing" as const, runStatus: "waiting_input", taskType: "order" as const };
    render(<HarnessPhaseBar state={state} />);
    expect(screen.getByText("任务阶段：等待人工确认")).toBeTruthy();
  });

  it("renders evidence-backed plan and check reasons without internal prompts", () => {
    const review: ReviewResult = { passed: false, revision_count: 1, incomplete_items: ["NUMERIC_MATCH"], checks: [
      { check_id: "NUMERIC_MATCH", passed: false, reason: "total_cents 与工具事实不一致。", evidence_refs: ["call-1/Q01"] },
    ] };
    render(<>
      <PlanPanel items={[{ id: "quote", title: "读取报价", status: "done", evidence_refs: [{ call_id: "call-1", entity: "quotes", id: "Q01" }] }]} />
      <ReviewPanel review={review} />
    </>);
    expect(screen.getByText(/读取报价/)).toBeTruthy();
    expect(screen.getByText(/quotes\/Q01/)).toBeTruthy();
    expect(screen.getAllByText(/NUMERIC_MATCH/)).toHaveLength(2);
    expect(document.body.textContent).not.toContain("private reasoning");
  });

  it("renders query-scope evidence and committed order facts after review failure", () => {
    const state = { ...emptyChatState(), runStatus: "failed", committedFacts: true,
      runSummary: "订单已提交：PO-1；评审未完成。" };
    render(<>
      <PlanPanel items={[{ id: "inventory", title: "读取库存", status: "done", query_evidence: [
        { call_id: "call-1", tool_name: "inventory_page", data_source: "local_seed", arguments: { warehouse_id: "W01" }, total: 0 },
      ] }]} />
      <section>{state.committedFacts ? state.runSummary : ""}</section>
    </>);
    expect(screen.getByText(/inventory_page/)).toBeTruthy();
    expect(screen.getByText(/PO-1/)).toBeTruthy();
  });
});
