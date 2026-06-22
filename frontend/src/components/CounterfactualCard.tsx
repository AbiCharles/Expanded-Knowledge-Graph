/**
 * Counterfactual exploration — surface for "what-if" actions on a
 * completed case:
 *   • Run baseline (W5 / Beat 2) — see what a supervisor without the
 *     governed knowledge layer would have surfaced
 *   • Replay with different decision — re-run with a forced reviewer call
 *   • Compare side-by-side — open the comparison modal against siblings
 *
 * Mirrors the ActionLifecycleCard pattern: prominent in the main case
 * view, sticky at the top of the Envelope so it's visible without
 * scrolling. Replaces the buried "↻ Replay with different decision"
 * panel that used to live in the Console history sidebar.
 *
 * Only renders on HITL-completed cases (case has a decision_kind that
 * isn't `auto_execute`). Baseline-replay cases hide it (you shouldn't
 * replay a baseline).
 */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { CaseFull, DecisionKind } from "../types";
import { ReviseTrigger, listReviseTriggers, reviseCase } from "../api";

interface Props {
  active: CaseFull | null;
  onReplay: (caseId: string, decision: DecisionKind) => void;
  onBaselineReplay: (caseId: string) => void;
  onCompare: (caseId: string) => void;
  baselineRunning?: boolean;
  onRevised?: () => void;
  // Tells the Envelope to open the knowledge-graph modal pre-selected to
  // the Decision-pathways tab. Called from the OK button of the
  // post-revision modal that lands once a trigger seals a new revision.
  onOpenPathways?: () => void;
}

const ALL_DECISIONS: DecisionKind[] = ["approve", "reject", "request_more_info"];

const DECISION_LABELS: Record<DecisionKind, string> = {
  approve: "Approve",
  reject: "Reject",
  request_more_info: "Request more info",
};

export function CounterfactualCard({
  active,
  onReplay,
  onBaselineReplay,
  onCompare,
  baselineRunning = false,
  onRevised,
  onOpenPathways,
}: Props) {
  // Tick once a second while baseline is running so the button label shows
  // the elapsed seconds. Resets when the running state clears.
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!baselineRunning) {
      setElapsed(0);
      return;
    }
    const start = Date.now();
    const t = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    return () => clearInterval(t);
  }, [baselineRunning]);

  // W1 / Beat 3 — fetch the available triggers for this case's scenario.
  const [triggers, setTriggers] = useState<ReviseTrigger[]>([]);
  const [supportsGenericRefresh, setSupportsGenericRefresh] = useState(false);
  const [revising, setRevising] = useState<string | null>(null);
  const [revisionStatus, setRevisionStatus] = useState<string | null>(null);
  // Post-revision modal — surfaced as soon as a narrative trigger seals a
  // new revision. Carries the trigger label + new decision so the
  // reviewer knows what just landed. OK closes the modal AND deep-links
  // into the knowledge-graph modal on the Decision-pathways tab so the
  // re-rendered pathways are the next thing the reviewer sees.
  const [reversionAnnouncement, setReversionAnnouncement] = useState<
    | {
        triggerLabel: string;
        newDecision?: string;
        revisionNo: number;
        explainer?: string;
      }
    | null
  >(null);
  const caseId = active?.case_id;
  useEffect(() => {
    if (!caseId) {
      setTriggers([]);
      return;
    }
    let cancelled = false;
    listReviseTriggers(caseId)
      .then((res) => {
        if (cancelled) return;
        setTriggers(res.triggers);
        setSupportsGenericRefresh(res.supports_generic_refresh);
      })
      .catch(() => {
        if (!cancelled) {
          setTriggers([]);
          setSupportsGenericRefresh(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [caseId]);

  const handleRevise = async (triggerId: string) => {
    if (!caseId || revising) return;
    setRevising(triggerId);
    setRevisionStatus(null);
    try {
      const res = await reviseCase(caseId, triggerId);
      if (res.no_change) {
        // Generic refresh in demo mode — terse status, no verbose
        // production-mode explanation in the UI.
        setRevisionStatus("No new evidence — no revision sealed.");
      } else {
        setRevisionStatus(
          `v${res.revision_no} sealed${
            res.new_decision ? ` · decision: ${res.new_decision}` : ""
          }`,
        );
        onRevised?.();
        // Show the modal for narrative triggers only. generic_refresh is
        // a demo-driving control with no story to tell.
        if (triggerId !== "generic_refresh") {
          const t = triggers.find((tr) => tr.id === triggerId);
          setReversionAnnouncement({
            triggerLabel: t?.label ?? res.trigger_label ?? "New evidence",
            newDecision: res.new_decision ?? undefined,
            revisionNo: res.revision_no,
            explainer: t?.explainer,
          });
        }
      }
    } catch (e) {
      console.error("Revise failed:", e);
      setRevisionStatus("Re-version failed — see console.");
    } finally {
      setRevising(null);
    }
  };
  if (!active) return null;
  // Only show on HITL-completed cases — counterfactuals don't apply to a
  // case that's still in progress, or an auto-execute path with no
  // reviewer decision to replay.
  const isHitlComplete =
    active.phase === "complete" &&
    !!active.decision_kind &&
    active.decision_kind !== "auto_execute";
  if (!isHitlComplete) return null;
  // Don't surface counterfactuals on the baseline replays themselves —
  // they're already a counterfactual of the original.
  if (active.baseline) return null;

  const currentDecision = active.decision_kind as DecisionKind;
  const alternatives = ALL_DECISIONS.filter((d) => d !== currentDecision);
  const siblingCount = (active.sibling_case_ids ?? []).length;

  return (
    <section className="counterfactual-card">
      <header className="counterfactual-head">
        <span className="counterfactual-eyebrow">Counterfactual exploration</span>
      </header>

      {/* Run baseline — Beat 2 */}
      <div className="counterfactual-section">
        <div className="counterfactual-section-head">
          <span className="counterfactual-icon" aria-hidden="true">☁</span>
          <span className="counterfactual-section-title">Run baseline</span>
        </div>
        <p className="counterfactual-section-desc">
          See what a supervisor <em>without</em> the governed knowledge
          layer would have surfaced — the review-stage queries are
          skipped, the case auto-approves, and the comparison opens
          automatically when the run completes.
        </p>
        <div className="counterfactual-section-actions">
          <button
            type="button"
            className={
              "counterfactual-btn counterfactual-btn-primary" +
              (baselineRunning ? " is-running" : "")
            }
            onClick={() => onBaselineReplay(active.case_id)}
            disabled={baselineRunning}
          >
            {baselineRunning
              ? `Running baseline… ${elapsed}s`
              : "Run baseline"}
          </button>
        </div>
      </div>

      {/* Replay with different decision */}
      <div className="counterfactual-section">
        <div className="counterfactual-section-head">
          <span className="counterfactual-icon" aria-hidden="true">↻</span>
          <span className="counterfactual-section-title">
            Replay with different decision
          </span>
        </div>
        <p className="counterfactual-section-desc">
          Re-run the same case with a forced reviewer decision to see how
          the outcome would have changed.
        </p>
        <div className="counterfactual-section-actions">
          {alternatives.map((d) => (
            <button
              key={d}
              type="button"
              className="counterfactual-btn counterfactual-btn-secondary"
              onClick={() => onReplay(active.case_id, d)}
            >
              {DECISION_LABELS[d]}
            </button>
          ))}
        </div>
      </div>

      {/* Simulate new evidence — W1 / Beat 3 */}
      {(triggers.length > 0 || supportsGenericRefresh) && (
        <div className="counterfactual-section">
          <div className="counterfactual-section-head">
            <span className="counterfactual-icon" aria-hidden="true">⚡</span>
            <span className="counterfactual-section-title">
              Simulate new evidence
              {(active.revisions?.length ?? 0) > 1 && (
                <span className="counterfactual-count has-siblings">
                  (currently at v{active.current_revision ?? active.revisions?.length ?? 1})
                </span>
              )}
            </span>
          </div>
          <p className="counterfactual-section-desc">
            Trigger a fresh-evidence event. The harness re-decides the
            case in place — v1 stays sealed on the audit trail, v2 (the
            new decision) renders above with the new fact highlighted.
          </p>
          <div className="counterfactual-section-actions counterfactual-trigger-grid">
            {triggers.map((t) => (
              <button
                key={t.id}
                type="button"
                className="counterfactual-btn counterfactual-btn-trigger"
                onClick={() => handleRevise(t.id)}
                disabled={!!revising}
                title={t.explainer}
              >
                {revising === t.id ? "Re-versioning…" : t.label}
              </button>
            ))}
          </div>
          {supportsGenericRefresh && (
            <div className="counterfactual-subsection">
              <div className="counterfactual-subsection-label">
                Or check for any silent change
              </div>
              <p className="counterfactual-subsection-desc">
                Re-runs the case's proposal + review queries against the
                live data sources, with no synthetic trigger injected.
                If nothing material has changed since v1 sealed, no new
                revision is created — useful for spot-checking that the
                facts behind the decision are still current.
              </p>
              <button
                type="button"
                className="counterfactual-btn counterfactual-btn-secondary"
                onClick={() => handleRevise("generic_refresh")}
                disabled={!!revising}
              >
                {revising === "generic_refresh"
                  ? "Refreshing…"
                  : "Re-run queries against current data"}
              </button>
            </div>
          )}
          {revisionStatus && (
            <div className="counterfactual-revision-status">
              {revisionStatus}
            </div>
          )}
        </div>
      )}

      {/* Compare with siblings */}
      <div className="counterfactual-section">
        <div className="counterfactual-section-head">
          <span className="counterfactual-icon" aria-hidden="true">⇄</span>
          <span className="counterfactual-section-title">
            Compare side-by-side
            <span
              className={
                "counterfactual-count" +
                (siblingCount > 0 ? " has-siblings" : "")
              }
            >
              ({siblingCount} sibling{siblingCount === 1 ? "" : "s"})
            </span>
          </span>
        </div>
        <p className="counterfactual-section-desc">
          {siblingCount === 0 ? (
            <>
              Activates after you create a sibling case via <b>Run baseline</b>
              {" "}or <b>Replay with a different decision</b> above. The modal
              renders this case next to each sibling with the load-bearing
              facts highlighted, so you can read what the harness saw that
              the alternate run didn't.
            </>
          ) : (
            <>
              {siblingCount} sibling{siblingCount === 1 ? "" : "s"} ready
              to compare. The modal renders this case next to each sibling
              with the load-bearing facts highlighted — auto-orders harness
              on the left vs baseline on the right when a baseline sibling
              exists.
            </>
          )}
        </p>
        <div className="counterfactual-section-actions">
          <button
            type="button"
            className="counterfactual-btn counterfactual-btn-secondary"
            onClick={() => onCompare(active.case_id)}
            disabled={siblingCount === 0}
            title={
              siblingCount === 0
                ? "No siblings yet — click Run baseline or one of the Replay buttons above."
                : undefined
            }
          >
            Compare
          </button>
        </div>
      </div>
      {reversionAnnouncement && (
        <ReversionAnnouncementModal
          triggerLabel={reversionAnnouncement.triggerLabel}
          newDecision={reversionAnnouncement.newDecision}
          revisionNo={reversionAnnouncement.revisionNo}
          explainer={reversionAnnouncement.explainer}
          onConfirm={() => {
            setReversionAnnouncement(null);
            onOpenPathways?.();
          }}
          onClose={() => setReversionAnnouncement(null)}
        />
      )}
    </section>
  );
}

function ReversionAnnouncementModal({
  triggerLabel,
  newDecision,
  revisionNo,
  explainer,
  onConfirm,
  onClose,
}: {
  triggerLabel: string;
  newDecision?: string;
  revisionNo: number;
  explainer?: string;
  onConfirm: () => void;
  onClose: () => void;
}) {
  // Portal to document.body so the modal escapes the
  // .counterfactual-card stacking context (position:sticky + z-index:4).
  // Without the portal, the modal's z-index:1500 is clipped to the
  // sticky parent's z-index and the scrim can end up behind the rest
  // of the Envelope content — which reads as "the app went blank".
  return createPortal(
    <div
      className="reversion-modal-scrim"
      role="dialog"
      aria-modal="true"
      aria-labelledby="reversion-modal-title"
      onClick={onClose}
    >
      <div
        className="reversion-modal-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="reversion-modal-eyebrow">
          ⚡ Case re-versioned by new evidence
        </div>
        <h2 id="reversion-modal-title" className="reversion-modal-title">
          v{revisionNo} sealed
          {newDecision && (
            <span className="reversion-modal-decision">
              {" · "}new decision: <strong>{newDecision}</strong>
            </span>
          )}
        </h2>
        <div className="reversion-modal-trigger">
          <span className="reversion-modal-trigger-label">Trigger</span>
          <span className="reversion-modal-trigger-text">{triggerLabel}</span>
        </div>
        {explainer && (
          <p className="reversion-modal-explainer">{explainer}</p>
        )}
        <p className="reversion-modal-cta-text">
          The knowledge graph + decision pathways have re-rendered to reflect
          this revision. Click <strong>OK</strong> to jump straight to the
          updated decision pathways view.
        </p>
        <div className="reversion-modal-actions">
          <button
            type="button"
            className="reversion-modal-btn reversion-modal-btn-secondary"
            onClick={onClose}
          >
            Stay here
          </button>
          <button
            type="button"
            className="reversion-modal-btn reversion-modal-btn-primary"
            onClick={onConfirm}
            autoFocus
          >
            OK · Show decision pathways
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
