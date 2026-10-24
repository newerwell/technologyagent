import type { ChatState } from "../../lib/event-reducer";

const labels: Record<NonNullable<ChatState["phase"]>, string> = {
  planning: "规划", executing: "执行", reviewing: "评审", result: "结果",
};

export function HarnessPhaseBar({ state }: { state: ChatState }) {
  const label = state.runStatus === "waiting_input" ? "等待人工确认"
    : state.runStatus === "failed" ? "执行失败"
      : state.runStatus === "cancelled" ? "已取消"
        : state.runStatus === "completed" ? (state.review?.passed ? "评审通过" : "已结束")
          : state.phase ? labels[state.phase] : "待开始";
  return <section className="card workflow-panel" aria-label="任务阶段" data-testid="harness-phase">
    <strong>任务阶段：{label}</strong>
    <span>类型：{state.taskType} · 修订：{state.revisionCount}/2</span>
  </section>;
}
