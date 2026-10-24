import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StatusPanel } from "./StatusPanel";
import type { Envelope } from "../../lib/api";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function envelope<T>(data: T): Envelope<T> {
  return {
    ok: true,
    data,
    error: null,
    meta: {
      request_id: "test-request",
      data_source: "none",
      as_of: "2026-10-23T00:00:00Z",
      scope: "local-owner",
    },
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("StatusPanel", () => {
  it("renders health, readiness, disabled capabilities and the local session", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/health") {
        return jsonResponse(envelope({ status: "ok", app: "TechnologyAgent", component: "api" }));
      }
      if (path === "/ready") {
        return jsonResponse(
          envelope({
            status: "ready",
            checks: {
              db: { status: "ok", detail: "primary reachable" },
              transaction: { status: "ok", detail: "commit/rollback transaction available" },
              model: { status: "disabled", reason: "P03" },
              mcp: { status: "disabled", reason: "P03" },
              sandbox: { status: "disabled", reason: "P06" },
            },
          }),
        );
      }
      if (path === "/api/session/me") {
        return jsonResponse(
          envelope({ owner_id: "local-owner", request_id: "r", mode: "local" }),
        );
      }
      throw new Error(`unexpected fetch: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<StatusPanel />);

    expect(await screen.findByText("后端已连接")).toBeInTheDocument();
    expect(await screen.findByText("本地会话已建立")).toBeInTheDocument();
    expect(screen.getByText("就绪")).toHaveClass("badge-ok");
    expect(screen.getByText("local-owner")).toBeInTheDocument();
    expect(screen.getByText("P02 · 流式对话")).toBeInTheDocument();
    expect(screen.getByText(/执行器明确为 FakeAgent/)).toBeInTheDocument();
    expect(screen.getByText(/P02 的对话从 \/chat 进入/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "进入对话" })).toHaveAttribute("href", "/chat");
    expect(screen.getByRole("link", { name: "进入业务数据" })).toHaveAttribute("href", "/data");
  });

  it("shows a readable error instead of an infinite loading state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("network down");
      }),
    );

    render(<StatusPanel />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getAllByText(/无法连接后端服务/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "重新检测" })).toBeInTheDocument();
  });
});
