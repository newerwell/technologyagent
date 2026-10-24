import type { ChatTool } from "../../lib/event-reducer";

export function ToolCards({ tools }: { tools: ChatTool[] }) {
  if (tools.length === 0) return null;
  return (
    <div className="tool-grid" data-testid="tool-cards">
      {tools.map((tool) => (
        <article key={tool.callId} className={"tool-card tool-" + tool.status} data-testid="tool-card">
          <header>
            <strong>{tool.name}</strong>
            <span className={"badge " + (tool.status === "success" ? "badge-ok" : tool.status === "error" ? "badge-error" : "badge-muted")}>
              {tool.status}
            </span>
          </header>
          <p>{tool.resultSummary || "等待假工具返回…"}</p>
          <small>
            {tool.simulation ? "模拟只读工具 · " : ""}
            {tool.source || "fake"} · call {tool.callId}
          </small>
          {tool.error ? <p className="error-text">{tool.error}</p> : null}
        </article>
      ))}
    </div>
  );
}
