import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MessageList } from "./MessageList";

describe("MessageList historical model attribution", () => {
  it("labels each assistant message from its own persisted run mode", () => {
    render(<MessageList messages={[
      { id: "live", role: "assistant", content: "from live", createdAt: "1", runId: "r1", streaming: false, modelMode: "live" },
      { id: "fake", role: "assistant", content: "from fake", createdAt: "2", runId: "r2", streaming: false, modelMode: "fake" },
      { id: "unknown", role: "assistant", content: "old record", createdAt: "3", runId: "r0", streaming: false, modelMode: null },
    ]} streaming={false} modelLabel="Live Model" />);
    expect(screen.getByText("Live Model")).toBeTruthy();
    expect(screen.getByText("ScriptedModel")).toBeTruthy();
    expect(screen.getByText("模式未知")).toBeTruthy();
  });
});
