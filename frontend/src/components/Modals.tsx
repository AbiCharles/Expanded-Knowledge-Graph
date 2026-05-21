import { useEffect, useMemo, useState } from "react";
import { CaseFull, DecisionKind } from "../types";

// =============================================================================
// Teams card modal
// =============================================================================
export function TeamsCardModal({
  active,
  onClose,
  onDecision,
}: {
  active: CaseFull;
  onClose: () => void;
  onDecision: (d: DecisionKind) => void;
}) {
  const sc = active.scenario!;
  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="teams-card">
        <div className="teams-header">
          <div className="teams-icon">T</div>
          <div>
            <div className="teams-app-name">TCS Knowledge Fabric · Reviewer</div>
            <div className="teams-channel">{sc.teams_channel}</div>
          </div>
          <button className="teams-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="teams-body">
          <div className="tc-headline">{sc.teams_headline}</div>
          <div className="tc-sub">
            Case {active.case_id} · Ticket{" "}
            {active.lineage.find((l) => l.action === "submitted")?.detail?.match(/async-[a-f0-9]+/)?.[0] ?? "—"}
          </div>

          <div className="tc-section-label">Proposed action</div>
          <div className="tc-action-detail">
            <ActionPayload caseFull={active} />
          </div>

          {active.stages.map((s) => (
            <div key={s.stage}>
              <div className="tc-section-label">
                {s.stage.replace("_", " ")} · {s.binder}
              </div>
              {s.facts.map((f) => (
                <div className="tc-fact" key={`${f.source}-${f.id}`}>
                  <div className="tc-fact-title">
                    {f.title}{" "}
                    <span style={{ color: "var(--ink-muted)", fontWeight: 400 }}>
                      · {f.ontology_type}:{f.id}
                    </span>
                  </div>
                  <div className="tc-fact-payload">{f.summary}</div>
                </div>
              ))}
            </div>
          ))}
        </div>
        <div className="teams-actions">
          <button className="tc-btn tc-btn-approve" onClick={() => onDecision("approve")}>
            Approve
          </button>
          <button className="tc-btn tc-btn-info" onClick={() => onDecision("request_more_info")}>
            Need more info
          </button>
          <button className="tc-btn tc-btn-reject" onClick={() => onDecision("reject")}>
            Reject
          </button>
        </div>
      </div>
    </div>
  );
}

function ActionPayload({ caseFull }: { caseFull: CaseFull }) {
  // We don't have the action object directly on CaseFull — show scenario-derived payload
  // by extracting from action_payload via /api/scenarios is overkill. Render a
  // compact summary from the lineage detail.
  const detail = caseFull.lineage.find((l) => l.action === "bound" && l.stage === "proposal")?.detail;
  return (
    <>
      <div>
        <span className="k">action_type</span>
        {caseFull.scenario?.id || ""}
      </div>
      <div>
        <span className="k">case_id</span>
        {caseFull.case_id}
      </div>
      {detail && (
        <div>
          <span className="k">proposal</span>
          {detail}
        </div>
      )}
    </>
  );
}

// =============================================================================
// Rationale modal — two views: edit + confirm
// =============================================================================
export function RationaleModal({
  active,
  decision,
  onClose,
  onSubmit,
}: {
  active: CaseFull;
  decision: "reject" | "request_more_info";
  onClose: () => void;
  onSubmit: (rationale: string, followUp: string | null) => void;
}) {
  const isReject = decision === "reject";
  const reasons = active.scenario?.rationale_reasons?.[decision] ?? [];
  const [text, setText] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [view, setView] = useState<"edit" | "confirm">("edit");

  return (
    <div
      className="modal-backdrop layer-2"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="rationale-card">
        <div className={`rationale-header${isReject ? "" : " mode-info"}`}>
          <div className="rationale-eyebrow">Reviewer rationale required</div>
          <div className="rationale-title">{isReject ? "Decline this action" : "Request more information"}</div>
        </div>

        {view === "edit" && (
          <>
            <div className="rationale-body">
              <div className="rationale-section-label">Quick-pick reasons · click to fill</div>
              <div className="rationale-chips">
                {reasons.map((r) => (
                  <button
                    key={r}
                    className={`rationale-chip${text === r ? " selected" : ""}`}
                    onClick={() => setText(r)}
                  >
                    {r}
                  </button>
                ))}
              </div>

              <div className="rationale-section-label">Reason</div>
              <textarea
                className="rationale-textarea"
                placeholder="Type or edit the reason for your decision…"
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && text.trim().length >= 4)
                    setView("confirm");
                }}
              />

              <div className="rationale-section-label" style={{ marginTop: 18 }}>
                Follow-up reminder · optional
              </div>
              <div className="followup-chips">
                {[
                  ["", "No follow-up"],
                  ["24h", "24 hours"],
                  ["3d", "3 days"],
                  ["1w", "1 week"],
                ].map(([val, label]) => (
                  <button
                    key={val}
                    className={`fu-chip${followUp === val ? " selected" : ""}`}
                    onClick={() => setFollowUp(val)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="rationale-help">
                This reason and any follow-up will be recorded in the audit lineage and shown back to the operator.
              </div>
            </div>
            <div className="rationale-footer">
              <button className="rationale-cancel" onClick={onClose}>
                ← Back to review
              </button>
              <button
                className={`rationale-submit${isReject ? "" : " mode-info"}`}
                disabled={text.trim().length < 4}
                onClick={() => setView("confirm")}
              >
                Continue
              </button>
            </div>
          </>
        )}

        {view === "confirm" && (
          <>
            <div className="rationale-body">
              <div className={`confirm-warning${isReject ? " mode-reject" : ""}`}>
                <div className="confirm-icon">!</div>
                <div className="confirm-warning-text">
                  <strong>{isReject ? "Are you sure you want to reject this action?" : "Are you sure you want to request more information?"}</strong>
                  <div>
                    {isReject
                      ? "Once submitted, this decision is recorded in the audit log and the agent is notified. The action will be aborted."
                      : "Once submitted, the case loops back to review with your questions appended. The agent will not execute until you decide again."}
                  </div>
                </div>
              </div>
              <div className="rationale-section-label">Your reason</div>
              <div className="confirm-quote">"{text}"</div>
              {followUp && (
                <>
                  <div className="rationale-section-label">Follow-up</div>
                  <div className="confirm-followup">⏱ Revisit in {followUpLabel(followUp)}</div>
                </>
              )}
            </div>
            <div className="rationale-footer">
              <button className="rationale-cancel" onClick={() => setView("edit")}>
                ← Back to edit
              </button>
              <button
                className={`rationale-submit${isReject ? "" : " mode-info"}`}
                onClick={() => onSubmit(text, followUp || null)}
              >
                {isReject ? "Yes, reject" : "Yes, send back"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function followUpLabel(fu: string): string {
  if (fu === "24h") return "24 hours";
  if (fu === "3d") return "3 days";
  if (fu === "1w") return "1 week";
  return fu;
}

// =============================================================================
// Approve confirmation modal
// =============================================================================
export function ApproveModal({
  active,
  onCancel,
  onConfirm,
}: {
  active: CaseFull;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const msg = active.scenario?.execute_message || "The agent will proceed with this action.";
  return (
    <div className="modal-backdrop layer-2" onClick={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="approve-card">
        <div className="approve-header">
          <div className="approve-eyebrow">Confirm action</div>
          <div className="approve-title">Confirm execute</div>
        </div>
        <div className="approve-body">
          <div className="approve-msg" dangerouslySetInnerHTML={{ __html: msg }} />
        </div>
        <div className="approve-footer">
          <button className="rationale-cancel" onClick={onCancel}>
            Cancel
          </button>
          <button className="approve-submit" onClick={onConfirm}>
            Confirm execute
          </button>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Auto-approve badge (autonomous scenarios)
// =============================================================================
export function AutoApproveModal({
  guardrailId,
  reason,
  onClose,
}: {
  guardrailId: string;
  reason: string;
  onClose: () => void;
}) {
  // Auto-dismiss after ~1.8s
  useEffect(() => {
    const t = setTimeout(onClose, 1800);
    return () => clearTimeout(t);
  }, [onClose]);

  return (
    <div className="modal-backdrop">
      <div className="auto-card">
        <div className="auto-header">
          <div className="auto-eyebrow">Autonomous decision</div>
          <div className="auto-title">Auto-approved by guardrail</div>
        </div>
        <div className="auto-body">
          <div className="auto-guardrail">{guardrailId}</div>
          <div className="auto-reason">{reason}</div>
        </div>
        <div className="auto-footer">No human review required · executing autonomously</div>
      </div>
    </div>
  );
}

// =============================================================================
// Comparison modal — fetches both cases and renders side by side
// =============================================================================
export function CompareModal({
  cases,
  onClose,
}: {
  cases: [CaseFull, CaseFull];
  onClose: () => void;
}) {
  const [a, b] = useMemo(() => cases, [cases]);
  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="compare-modal">
        <div className="compare-header">
          <div className="compare-title">Side-by-side replay comparison</div>
          <button className="compare-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="compare-body">
          <CompareSide caseFull={a} kind={a.replay_decision ? "replay" : "original"} />
          <div className="compare-divider" />
          <CompareSide caseFull={b} kind={b.replay_decision ? "replay" : "original"} />
        </div>
      </div>
    </div>
  );
}

function CompareSide({ caseFull, kind }: { caseFull: CaseFull; kind: "original" | "replay" }) {
  const sc = caseFull.scenario;
  const decision = caseFull.decision_kind || "—";
  const o = sc?.outcomes?.[decision];
  const decisionColor =
    decision === "approve"
      ? "var(--emerald)"
      : decision === "reject"
      ? "var(--crimson)"
      : "var(--amber)";
  const decisionLabel = decision === "request_more_info" ? "More info" : decision;

  return (
    <div className="compare-side">
      <div className="compare-side-eyebrow">
        {caseFull.case_id} · {kind}
      </div>
      <div className="compare-side-headline">{sc?.title}</div>

      <div className="compare-block">
        <div className="compare-block-label">Operator prompt</div>
        <div className="compare-block-content">{caseFull.prompt}</div>
      </div>
      <div className="compare-block" style={{ borderColor: decisionColor }}>
        <div className="compare-block-label" style={{ color: decisionColor }}>
          Reviewer decision · {decisionLabel}
        </div>
        <div className="compare-block-content">
          <strong>{o?.headline}</strong>
          <br />
          {o?.detail}
        </div>
      </div>
      {caseFull.lineage.find((l) => l.action === "decided")?.detail && (
        <div className="compare-block" style={{ borderColor: decisionColor }}>
          <div className="compare-block-label" style={{ color: decisionColor }}>
            Reviewer's reason
          </div>
          <div className="compare-block-content" style={{ fontStyle: "italic" }}>
            "{caseFull.lineage.find((l) => l.action === "decided")?.detail}"
          </div>
        </div>
      )}
      <div className="compare-block">
        <div className="compare-block-label">Lineage</div>
        <div className="compare-block-content">
          {caseFull.lineage.map((ev) => (
            <div className="compare-lineage-event" key={ev.sequence}>
              <span className="seq">#{String(ev.sequence).padStart(2, "0")}</span>
              {ev.stage} · {ev.actor} — {ev.detail}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
