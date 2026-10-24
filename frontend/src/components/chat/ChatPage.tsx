"use client";

import { useEffect, useState } from "react";

import { useChat } from "../../hooks/useChat";
import { ConversationList } from "../sidebar/ConversationList";
import { Composer } from "./Composer";
import { MessageList } from "./MessageList";
import { ToolCards } from "./ToolCards";
import { getDraft, type OrderDraftView } from "../../lib/api";
import { ApprovalCard } from "../approval/ApprovalCard";
import { SupplementForm } from "../approval/SupplementForm";
import { HarnessPhaseBar } from "../workflow/HarnessPhaseBar";
import { PlanPanel } from "../workflow/PlanPanel";
import { ReviewPanel } from "../workflow/ReviewPanel";

export function ChatPage() {
  const chat = useChat();
  const [draftThreadId, setDraftThreadId] = useState<string | null>(null);
  const [workflowDraft, setWorkflowDraft] = useState<OrderDraftView | null>(null);
  const [warehouseId, setWarehouseId] = useState("");
  const [draftQuantity, setDraftQuantity] = useState(55);
  const activeThread = chat.state.threadId ?? draftThreadId;
  const modelLabel = chat.state.modelMode === "live" ? "Live Model" : "ScriptedModel";
  const modeText = chat.state.modelMode === "live" ? "live" : "fake";

  useEffect(() => {
    const draftId = chat.state.pendingInterrupt?.draft_id;
    if (!draftId) { setWorkflowDraft(null); return; }
    let current = true;
    void getDraft(draftId).then((result) => { if (current) {
      setWorkflowDraft(result.data);
      if (result.data?.items[0]) setDraftQuantity(result.data.items[0].quantity);
    } }).catch(() => { if (current) setWorkflowDraft(null); });
    return () => { current = false; };
  }, [chat.state.pendingInterrupt?.draft_id, chat.state.pendingInterrupt?.version]);

  return (
    <main className="shell chat-shell">
      <header className="hero data-hero">
        <div>
          <p className="eyebrow">P03 · 只读采购助手</p>
          <h1>有工具依据的对话</h1>
          <p className="lede">
            P03 工具只读查询本地库存、供应商、报价和补货规则；
            P04 订单必须通过明确的审批中断创建。当前模式：{modelLabel}（model_mode={modeText}）。
          </p>
        </div>
        <div className="hero-actions">
          <a className="nav-link" href="/">
            返回工程状态
          </a>
          <a className="nav-link" href="/data">
            业务数据
          </a>
          <a className="nav-link" href="/orders">订单审批</a>
          <span className="badge badge-muted" data-testid="fake-badge">
            {modelLabel} · model_mode={modeText}
          </span>
          <button type="button" onClick={() => void chat.refresh()} disabled={chat.sending}>
            刷新 / 恢复
          </button>
        </div>
      </header>

      {chat.error ? (
        <section className="alert" role="alert">
          <strong>对话操作失败</strong>
          <p>{chat.error}</p>
          <p className="hint">已有事件仍可从持久化历史恢复；刷新只会重连观察，不会取消后台任务。</p>
        </section>
      ) : null}
      {chat.notice ? (
        <section className="notice" role="status">
          {chat.notice}
          <button type="button" onClick={chat.dismissNotice}>关闭</button>
        </section>
      ) : null}

      <div className="chat-layout">
        <ConversationList
          conversations={chat.conversations}
          activeThreadId={activeThread}
          loading={chat.historyLoading}
          onSelect={(threadId) => {
            setDraftThreadId(threadId);
            void chat.selectThread(threadId);
          }}
          onNew={() => {
            setDraftThreadId(null);
            chat.newChat();
          }}
        />

        <section className="card chat-main" aria-label="对话">
          <div className="chat-toolbar">
            <div>
              <span className="pill">thread {chat.state.threadId?.slice(0, 16) ?? "未开始"}</span>
              <span className="pill">run {chat.state.runId?.slice(0, 16) ?? "-"}</span>
              <span className="pill">status {chat.state.runStatus ?? "idle"}</span>
            </div>
            <span className="badge badge-muted">{modelLabel} · {modeText === "live" ? "真实模型" : "离线脚本"}</span>
          </div>

          <MessageList messages={chat.state.messages} streaming={chat.busy} modelLabel={modelLabel} />
          <HarnessPhaseBar state={chat.state} />
          {chat.state.committedFacts && chat.state.runStatus !== "completed" ? <section className="card" role="status" data-testid="committed-facts">
            <h2>业务结果已提交，说明评审未通过</h2>
            <p>{chat.state.runSummary || "已保留数据库中的提交结果；未自动重放订单。"}</p>
          </section> : null}
          <PlanPanel items={chat.state.plan} />
          <ReviewPanel review={chat.state.review} />
          <ToolCards tools={chat.state.tools} />
          {chat.state.pendingInterrupt?.kind === "supplement" ? <section className="card" data-testid="workflow-supplement">
            <h2>补充订单信息</h2>
            <SupplementForm fields={chat.state.pendingInterrupt.fields ?? []} warehouseId={warehouseId} setWarehouseId={setWarehouseId} />
            <button type="button" onClick={() => void chat.resume({
              interrupt_id: chat.state.pendingInterrupt!.interrupt_id, decision: "supplement",
              expected_version: chat.state.pendingInterrupt!.version ?? null,
              payload: { warehouse_id: warehouseId }, idempotency_key: `supplement_${chat.state.runId}`,
            })}>继续</button>
          </section> : null}
          {chat.state.pendingInterrupt?.kind === "approval" && workflowDraft ? <ApprovalCard
            draft={workflowDraft} quantity={draftQuantity} busy={chat.busy}
            onQuantity={setDraftQuantity}
            onEdit={() => void chat.resume({
              interrupt_id: chat.state.pendingInterrupt!.interrupt_id, decision: "edit",
              expected_version: chat.state.pendingInterrupt!.version ?? null,
              payload: { items: workflowDraft.items.map((item) => ({ part_id: item.part_id, quote_id: item.quote_id, quantity: draftQuantity })) },
              idempotency_key: `edit_${chat.state.runId}_${workflowDraft.version}`,
            })}
            onApprove={() => void chat.resume({
              interrupt_id: chat.state.pendingInterrupt!.interrupt_id, decision: "approve",
              expected_version: chat.state.pendingInterrupt!.version ?? null,
              idempotency_key: `approve_${chat.state.runId}_${workflowDraft.version}`,
            })}
            onReject={() => void chat.resume({
              interrupt_id: chat.state.pendingInterrupt!.interrupt_id, decision: "reject",
              expected_version: chat.state.pendingInterrupt!.version ?? null,
              idempotency_key: `reject_${chat.state.runId}_${workflowDraft.version}`,
            })}
          /> : null}

          <Composer
            busy={chat.busy || chat.state.runStatus === "waiting_input"}
            sending={chat.sending}
            canCancel={Boolean(chat.state.runId && ["running", "waiting_input"].includes(chat.state.runStatus ?? ""))}
            onSend={(value) => void chat.send(value)}
            onCancel={() => void chat.cancel()}
          />
        </section>
      </div>

      <footer className="footer">
        <span>SSE: POST /api/chat/stream · 事件按 run+seq 去重</span>
        <span>历史: GET /api/conversations · 查询: GET /api/runs/{"{id}"}/events</span>
      </footer>
    </main>
  );
}
