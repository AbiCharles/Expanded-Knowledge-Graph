import { useState } from "react";
import { CaseFull, CaseSummary, DecisionKind, ScenarioRow } from "../types";

interface Props {
  scenarios: ScenarioRow[];
  cases: CaseSummary[];
  active: CaseFull | null;
  role: "operator" | "reviewer";
  composerLocked: boolean;
  onSendPrompt: (text: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
  onSelectCase: (caseId: string | null) => void;
  onReplay: (caseId: string, decision: DecisionKind) => void;
  onCompare: (caseId: string) => void;
  onOpenReview: () => void;
  onPickCandidate: (scenarioId: string) => void;
  onDeleteCase: (caseId: string) => void;
  onClearCompleted: () => void;
  onEditScenario: (scenarioId: string) => void;
}

export function Console({
  scenarios,
  cases,
  active,
  role,
  composerLocked,
  onSendPrompt,
  onConfirm,
  onCancel,
  onSelectCase,
  onReplay,
  onCompare,
  onOpenReview,
  onPickCandidate,
  onDeleteCase,
  onClearCompleted,
  onEditScenario,
}: Props) {
  const [text, setText] = useState("");
  const [replayOpen, setReplayOpen] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const send = () => {
    if (!text.trim() || composerLocked) return;
    onSendPrompt(text);
    setText("");
  };

  // When a case is being viewed, the chat thread fills the panel.
  // Otherwise: default to a clean welcome; toggle to show history.
  const showWelcome = !active && !showHistory;
  const showHistoryList = !active && showHistory;
  const historyCount = cases.length;

  return (
    <aside className={`console${role === "reviewer" ? " dimmed" : ""}`}>
      <div className="console-header">
        <div className="console-header-row">
          <div>
            <div className="console-eyebrow">Operator console</div>
            <div className="console-title">
              {active ? "Conversation" : showHistoryList ? "History" : "Start a conversation"}
            </div>
          </div>
          {!active && historyCount > 0 && (
            <button
              className={`history-toggle${showHistoryList ? " active" : ""}`}
              onClick={() => setShowHistory((v) => !v)}
              title={showHistoryList ? "Back to start" : "View past conversations"}
            >
              {showHistoryList ? "← Start" : `History (${historyCount})`}
            </button>
          )}
        </div>
        {!active && (
          <div className="console-subtitle">
            {showHistoryList
              ? "Click any past case to revisit it."
              : "Ask the agent to do work in plain language. The framework decides whether human review is required."}
          </div>
        )}
      </div>

      {active && (
        <ChatThread
          active={active}
          onConfirm={onConfirm}
          onCancel={onCancel}
          onBack={() => onSelectCase(null)}
          onOpenReview={onOpenReview}
          onReplay={(d) => onReplay(active.case_id, d)}
          onCompare={() => onCompare(active.case_id)}
          onPickCandidate={onPickCandidate}
        />
      )}
      {showHistoryList && (
        <ThreadList
          cases={cases}
          replayOpenFor={replayOpen}
          onSelect={(id) => {
            onSelectCase(id);
            setShowHistory(false);
          }}
          onToggleReplay={(id) => setReplayOpen(replayOpen === id ? null : id)}
          onReplay={(id, d) => onReplay(id, d)}
          onCompare={(id) => onCompare(id)}
          onDelete={onDeleteCase}
          onClearCompleted={onClearCompleted}
        />
      )}
      {showWelcome && <WelcomeState historyCount={historyCount} />}

      <div className="suggested-row">
        <div className="suggested-label">Suggested · click to use</div>
        <div className="suggested-chips">
          {[...scenarios]
            .sort((a, b) => (b.mtime ?? 0) - (a.mtime ?? 0))
            .map((sc) => (
            <div key={sc.id} className="chip-row">
              <button
                className="chip"
                disabled={composerLocked}
                onClick={() => onSendPrompt(sc.suggested_prompt)}
                title={chipTooltip(sc)}
              >
                {sc.suggested_prompt}
                {sc.source_kinds && sc.source_kinds.length > 0 ? (
                  <span className="chip-sources">
                    {sc.source_kinds.map((k) => (
                      <span
                        key={k}
                        className={`chip-source-badge chip-source-${k}`}
                      >
                        {sourceKindLabel(k)}
                      </span>
                    ))}
                  </span>
                ) : null}
                {sc.run_count && sc.run_count > 0 ? (
                  <span className="chip-stat">· {sc.run_count}</span>
                ) : null}
              </button>
              <button
                className="chip-edit"
                onClick={(e) => {
                  e.stopPropagation();
                  onEditScenario(sc.id);
                }}
                title={`Edit ${sc.id}`}
                aria-label={`Edit ${sc.id}`}
              >
                ✎
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="composer">
        <textarea
          placeholder="Ask the agent to do something…"
          value={text}
          disabled={composerLocked}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button onClick={send} disabled={composerLocked || !text.trim()}>
          Send
        </button>
      </div>
    </aside>
  );
}

// =============================================================================
// Sub-components
// =============================================================================
function ThreadList({
  cases,
  replayOpenFor,
  onSelect,
  onToggleReplay,
  onReplay,
  onCompare,
  onDelete,
  onClearCompleted,
}: {
  cases: CaseSummary[];
  replayOpenFor: string | null;
  onSelect: (id: string) => void;
  onToggleReplay: (id: string) => void;
  onReplay: (id: string, d: DecisionKind) => void;
  onCompare: (id: string) => void;
  onDelete: (id: string) => void;
  onClearCompleted: () => void;
}) {
  if (cases.length === 0) {
    return (
      <div className="thread-list">
        <div className="thread-empty">
          No conversations yet. Pick a suggested prompt or type your own below.
        </div>
      </div>
    );
  }
  const completedCount = cases.filter((c) => c.phase === "complete").length;
  const doDelete = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm("Delete this case? This is permanent.")) onDelete(id);
  };
  const doClear = () => {
    if (completedCount === 0) return;
    if (confirm(`Clear ${completedCount} completed case${completedCount === 1 ? "" : "s"}?`)) {
      onClearCompleted();
    }
  };
  return (
    <div className="thread-list">
      <div className="thread-list-actions">
        <a
          className="thread-export-link"
          href="/api/exports/cases.csv"
          target="_blank"
          rel="noreferrer"
          title="Download all cases as CSV"
        >
          ↓ Export cases
        </a>
        <a
          className="thread-export-link"
          href="/api/exports/lineage.csv"
          target="_blank"
          rel="noreferrer"
          title="Download the full lineage / audit log as CSV"
        >
          ↓ Export lineage
        </a>
        {completedCount > 0 && (
          <button className="thread-clear-btn" onClick={doClear}>
            Clear completed ({completedCount})
          </button>
        )}
      </div>
      {cases
        .slice()
        .reverse()
        .map((c) => {
          const completed = c.phase === "complete";
          const status = completed ? c.decision_kind : c.phase === "cancelled" ? "cancelled" : "in-progress";
          const statusCls =
            status === "approve"
              ? "approve"
              : status === "reject"
              ? "reject"
              : status === "request_more_info"
              ? "more-info"
              : status === "auto_execute"
              ? "auto"
              : "in-progress";
          const statusText =
            status === "request_more_info"
              ? "more info"
              : status === "auto_execute"
              ? "auto-executed"
              : status === "in-progress"
              ? "in progress"
              : status || "";
          const alternatives = (["approve", "reject", "request_more_info"] as DecisionKind[]).filter(
            (d) => d !== c.decision_kind
          );
          const altLabels: Record<DecisionKind, string> = {
            approve: "Approve",
            reject: "Reject",
            request_more_info: "More info",
          };
          const isReplay = !!c.replay_decision;
          const hasSibling = (c.sibling_case_ids || []).length > 0;
          const hitlCompleted = completed && c.decision_kind && c.decision_kind !== "auto_execute";

          return (
            <div
              key={c.case_id}
              className={`thread-case${completed ? " completed" : ""}${isReplay ? " replay" : ""}${
                hasSibling ? " has-sibling" : ""
              }`}
              onClick={() => onSelect(c.case_id)}
            >
              <button
                className="thread-delete"
                onClick={(e) => doDelete(c.case_id, e)}
                title="Delete this case"
                aria-label="Delete this case"
              >
                ×
              </button>
              <div className="thread-meta">
                <span className="case-id">{c.case_id}</span>
                <span className={`thread-status ${statusCls}`}>{statusText}</span>
              </div>
              <div className="thread-prompt">{c.prompt}</div>

              {hitlCompleted && (
                <>
                  <div
                    className="thread-replay-link"
                    onClick={(e) => {
                      e.stopPropagation();
                      onToggleReplay(c.case_id);
                    }}
                  >
                    ↻ Replay with different decision
                  </div>
                  {replayOpenFor === c.case_id && (
                    <div className="thread-replay-options">
                      {alternatives.slice(0, 2).map((d) => (
                        <button
                          key={d}
                          onClick={(e) => {
                            e.stopPropagation();
                            onReplay(c.case_id, d);
                          }}
                        >
                          {altLabels[d]}
                        </button>
                      ))}
                    </div>
                  )}
                  {hasSibling && (
                    <div
                      className="thread-compare-link"
                      onClick={(e) => {
                        e.stopPropagation();
                        onCompare(c.case_id);
                      }}
                    >
                      ⇄ Compare side-by-side
                    </div>
                  )}
                </>
              )}
            </div>
          );
        })}
    </div>
  );
}

function ChatThread({
  active,
  onConfirm,
  onCancel,
  onBack,
  onOpenReview,
  onReplay,
  onCompare,
  onPickCandidate,
}: {
  active: CaseFull;
  onConfirm: () => void;
  onCancel: () => void;
  onBack: () => void;
  onOpenReview: () => void;
  onReplay: (d: DecisionKind) => void;
  onCompare: () => void;
  onPickCandidate: (scenarioId: string) => void;
}) {
  const sc = active.scenario;
  const messages: { role: "agent" | "operator" | "system"; html: string; demoHelper?: boolean }[] = [];

  messages.push({
    role: "system",
    html: `Case ${active.case_id}${sc ? " · " + sc.domain : ""}${
      active.replay_decision ? " · replay" : ""
    } · <a href="#" id="back-to-list" style="color:var(--cyan);text-decoration:none;">← all conversations</a>`,
  });

  // Operator initial prompt
  messages.push({ role: "operator", html: escapeHtml(active.prompt) });

  // Agent interpretation + clarifier (or follow-up confirmations)
  if (active.phase === "awaiting_clarification" && sc) {
    messages.push({
      role: "agent",
      html:
        `I read this as: <em>${escapeHtml(active.interpreted_as || "")}</em>.<br><br>` +
        (sc ? "" : "") +
        // Note: the clarifying question is loaded via getCase
        "",
    });
  }

  // We render the message strings *and* attach action buttons separately below
  // so React can wire onClick handlers cleanly.

  return (
    <div className="chat-thread">
      <ChatBubble role="system" html={messages[0].html} onBack={onBack} />
      <ChatBubble role="operator" html={escapeHtml(active.prompt)} />

      {/* Agent: interpretation + clarifier, or "routing" message during binding */}
      {(active.phase === "awaiting_clarification" ||
        active.phase === "binding" ||
        active.phase === "review_ready" ||
        active.phase === "reviewing" ||
        active.phase === "complete") && (
        <ChatBubble
          role="agent"
          html={
            sc
              ? `I read this as: <em>${escapeHtml(active.interpreted_as || "")}</em>.<br><br>${
                  active.phase === "awaiting_clarification"
                    ? active.clarifying_question || "Should I proceed with this action?"
                    : "Got it. Routing through the framework now."
                }`
              : active.clarifying_question ||
                "I'm not sure I can act on that yet. Try one of the suggested prompts."
          }
          actions={
            active.phase === "awaiting_clarification" ? (
              <>
                {sc && (
                  <div className="chat-confirm-row">
                    <button className="confirm-yes" onClick={onConfirm}>Yes, proceed</button>
                    <button className="confirm-no" onClick={onCancel}>Cancel</button>
                  </div>
                )}
                {shouldShowCandidates(active) && (
                  <DidYouMeanRow
                    active={active}
                    onPick={onPickCandidate}
                  />
                )}
              </>
            ) : null
          }
        />
      )}

      {/* Binding system note + spinner */}
      {(active.phase === "binding" || active.phase === "review_ready") && (
        <ChatBubble
          role="system"
          html={`routing through TCS Knowledge Fabric · case ${active.case_id}`}
        />
      )}

      {/* Review-ready CTA */}
      {active.phase === "review_ready" && (
        <ChatBubble
          role="agent"
          html={`Three stages bound — ${active.lineage.length} events on the audit trail. <strong>This action requires human review.</strong> The Adaptive Card is in the reviewer's Teams channel.`}
          actions={<button className="review-cta" onClick={onOpenReview}>View as reviewer →</button>}
        />
      )}

      {/* Final closing message */}
      {active.phase === "complete" && active.closing_message && (
        <>
          <ChatBubble
            role="system"
            html={
              active.decision_kind === "auto_execute"
                ? `auto-approved by ${
                    active.scenario?.auto_approval_guardrail || "policy"
                  } · executed without human review`
                : `decision recorded · returning to operator console`
            }
          />
          <ChatBubble role="agent" html={active.closing_message} />
          {active.decision_kind && active.decision_kind !== "auto_execute" && (
            <DemoHelper
              isReplay={!!active.replay_decision}
              hasSibling={(active.sibling_case_ids || []).length > 0}
              decision={active.decision_kind as DecisionKind}
              onReplay={onReplay}
              onCompare={onCompare}
            />
          )}
        </>
      )}

      {active.phase === "cancelled" && (
        <ChatBubble role="agent" html="OK, cancelled. Nothing was sent through the framework." />
      )}
    </div>
  );
}

function ChatBubble({
  role,
  html,
  actions,
  onBack,
}: {
  role: "agent" | "operator" | "system";
  html: string;
  actions?: React.ReactNode;
  onBack?: () => void;
}) {
  // System bubble may include the back link — wire it
  const bubble = (
    <div
      className="chat-bubble"
      onClick={(e) => {
        const target = e.target as HTMLElement;
        if (target.id === "back-to-list" && onBack) {
          e.preventDefault();
          onBack();
        }
      }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
  if (role === "system") return <div className="chat-msg system">{bubble}</div>;
  const avatar = role === "agent" ? "A" : "O";
  return (
    <div className={`chat-msg ${role}`}>
      <div className="chat-avatar">{avatar}</div>
      <div style={{ maxWidth: "80%" }}>
        {bubble}
        {actions}
      </div>
    </div>
  );
}

function DemoHelper({
  isReplay,
  hasSibling,
  decision,
  onReplay,
  onCompare,
}: {
  isReplay: boolean;
  hasSibling: boolean;
  decision: DecisionKind;
  onReplay: (d: DecisionKind) => void;
  onCompare: () => void;
}) {
  const alternatives = (["approve", "reject", "request_more_info"] as DecisionKind[]).filter(
    (d) => d !== decision
  );
  const labels: Record<DecisionKind, string> = {
    approve: "Approve",
    reject: "Reject",
    request_more_info: "Need more info",
  };
  return (
    <div className="chat-msg system demo-helper">
      <div className="chat-bubble">
        {isReplay && hasSibling ? (
          <>
            <div className="demo-helper-prompt">⇄ Compare with the original decision</div>
            <div className="demo-helper-actions">
              <button className="demo-helper-btn primary" onClick={onCompare}>
                Open side-by-side comparison
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="demo-helper-prompt">↻ See what happens with a different decision</div>
            <div className="demo-helper-actions">
              {alternatives.slice(0, 2).map((d) => (
                <button key={d} className="demo-helper-btn" onClick={() => onReplay(d)}>
                  {labels[d]}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// Show "Did you mean…?" when (a) we have no top match at all, or
// (b) classifier confidence is below the threshold and we have alternatives.
const SUGGEST_THRESHOLD = 0.7;

function shouldShowCandidates(active: CaseFull): boolean {
  const candidates = active.candidates || [];
  if (candidates.length === 0) return false;
  if (active.scenario_id == null) return true;
  if ((active.confidence ?? 1) < SUGGEST_THRESHOLD && candidates.length >= 2) return true;
  return false;
}

function DidYouMeanRow({
  active,
  onPick,
}: {
  active: CaseFull;
  onPick: (scenarioId: string) => void;
}) {
  const candidates = active.candidates || [];
  const lead =
    active.scenario_id == null
      ? "Pick the closest fit:"
      : `Or did you mean…?  (current confidence ${(active.confidence * 100).toFixed(0)}%)`;
  return (
    <div className="did-you-mean">
      <div className="did-you-mean-label">{lead}</div>
      <div className="did-you-mean-buttons">
        {candidates.map((c) => (
          <button
            key={c.scenario_id}
            className={`did-you-mean-btn${c.scenario_id === active.scenario_id ? " current" : ""}`}
            onClick={() => onPick(c.scenario_id)}
            disabled={c.scenario_id === active.scenario_id}
            title={`confidence ${(c.confidence * 100).toFixed(0)}%`}
          >
            <span className="did-you-mean-title">{c.title}</span>
            <span className="did-you-mean-conf">{(c.confidence * 100).toFixed(0)}%</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function WelcomeState({ historyCount }: { historyCount: number }) {
  return (
    <div className="welcome-state">
      <div className="welcome-eyebrow">Knowledge envelope</div>
      <div className="welcome-headline">
        Each case <em>builds an envelope</em> of bound knowledge as it moves through the flow.
      </div>
      <div className="welcome-body">
        <ul>
          <li>Pick a suggested prompt below, or write your own.</li>
          <li>The agent will read your request, propose an action, and bind facts at every stage.</li>
          <li>If the action needs human review, you'll see a Teams card.</li>
          <li>Lineage on the right records every step.</li>
        </ul>
        {historyCount > 0 && (
          <div className="welcome-hint">
            {historyCount} past conversation{historyCount === 1 ? "" : "s"} saved · use <strong>History</strong> above to revisit.
          </div>
        )}
        <div className="welcome-hint welcome-hint-quiet">
          Want to add your own scenarios?{" "}
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              window.dispatchEvent(new CustomEvent("open-scenarios-help"));
            }}
          >
            Read the authoring guide →
          </a>
        </div>
      </div>
    </div>
  );
}

function chipTooltip(sc: ScenarioRow): string {
  const lines = [`${sc.id} — ${sc.title}`];
  if (sc.source_ids && sc.source_ids.length > 0) {
    const kinds = sc.source_kinds && sc.source_kinds.length > 0
      ? ` (${sc.source_kinds.join(", ")})`
      : "";
    lines.push(`Backed by: ${sc.source_ids.join(", ")}${kinds}`);
  }
  if (typeof sc.run_count === "number" && sc.run_count > 0) {
    const parts = [`${sc.run_count} run${sc.run_count === 1 ? "" : "s"}`];
    if (sc.approve_count) parts.push(`${sc.approve_count} approved`);
    if (sc.reject_count) parts.push(`${sc.reject_count} rejected`);
    if (sc.auto_count) parts.push(`${sc.auto_count} auto-executed`);
    lines.push(parts.join(" · "));
    if (sc.last_run_at) {
      lines.push(`Last run: ${new Date(sc.last_run_at).toLocaleString()}`);
    }
  } else {
    lines.push("(never run)");
  }
  return lines.join("\n");
}

function sourceKindLabel(kind: string): string {
  switch (kind) {
    case "csv":
      return "CSV";
    case "sqlite":
      return "SQLite";
    case "postgres":
      return "Postgres";
    case "http":
      return "HTTP";
    case "vector_store":
      return "Vector";
    case "neo4j":
      return "Neo4j";
    default:
      return kind;
  }
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" } as Record<string, string>)[ch]
  );
}
