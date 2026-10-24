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
          <small>参数 {JSON.stringify(tool.argsSummary)}</small>
          <p>{tool.resultSummary || "等待只读工具返回…"}</p>
          <small>
            {tool.simulation ? "模拟只读工具 · " : "只读工具 · "}
            {tool.source || "unknown"} · call {tool.callId}
          </small>
          {tool.error ? <p className="error-text">{tool.error}</p> : null}
        </article>
      ))}
    </div>
  );
}
