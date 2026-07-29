/**
 * Full-screen pathway modal for a multi-scenario question.
 *
 * Shows the compose-then-branch graph plus the actionable VIABLE PATHWAYS the
 * reviewer can approve (most-probable tagged "Recommended"). Approving one
 * pathway executes it end-to-end (the backend auto-applies that path's
 * decisions and fires each step's action). Live progress overlays the actual
 * path onto the graph.
 */
import { useEffect } from "react";

import { PipelineForecast, PipelineState, ViablePath } from "../types";
import { OutcomeTreeGraph, OUTCOME_ACCENT, pct } from "./OutcomeTreeGraph";

const DECISION_LABEL: Record<string, string> = {
  approve: "approve",
  auto_execute: "auto-execute",
  reject: "reject",
  request_more_info: "more info",
};

export function PipelineModal({
  pipeline,
  pstate,
  onApprove,
  approving,
  onClose,
}: {
  pipeline: PipelineForecast;
  pstate: PipelineState | null;
  onApprove: (pathId: string) => void;
  approving: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const plan = pstate?.forecast ?? pipeline.forecast;
  const paths: ViablePath[] = pstate?.viable_paths ?? [];
  const status = pstate?.status ?? "planned";
  const chosen = pstate?.chosen_path_id ?? null;
  const activeScenarioId =
    status === "running" && pstate ? pstate.steps[pstate.current_step]?.scenario_id ?? null : null;

  const titleFor = (sid: string) =>
    (pstate?.steps ?? pipeline.steps).find((s) => s.scenario_id === sid)?.title ?? sid;

  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="ds-modal pw-modal" style={{ maxWidth: 1240, width: "95vw", height: "90vh" }}>
        <div className="ds-header">
          <div>
            <div className="ds-eyebrow">Multi-scenario reasoning</div>
            <h2 className="ds-title">Outcome pathways</h2>
            <p className="ds-sub">
              {status === "planned"
                ? "Pick one viable pathway to approve — the system will carry out every step for you."
                : status === "running"
                ? `Executing the approved pathway · step ${(pstate?.current_step ?? 0) + 1}…`
                : status === "complete"
                ? `Done — the pathway ran to completion (ended on ${pstate?.terminal_decision ?? "—"}).`
                : `Error: ${pstate?.error ?? "unknown"}`}
            </p>
          </div>
          <button className="graph-modal-close" type="button" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="pw-body">
          <div className="pw-graph">
            <OutcomeTreeGraph
              plan={plan}
              actualPath={pstate?.actual_path}
              activeScenarioId={activeScenarioId}
              runActive={status === "running"}
              hideOutcomes
            />
          </div>

          <aside className="pw-paths">
            <div className="pw-paths-head">Viable pathways ({paths.length})</div>
            <div className="pw-paths-hint">Each is a full course of action → outcome, ranked by likelihood.</div>
            <div className="pw-paths-list">
              {paths.map((p) => {
                const accent = OUTCOME_ACCENT[p.outcome_kind || ""] || "alt";
                const isChosen = chosen === p.path_id;
                return (
                  <div
                    key={p.path_id}
                    className={`pw-path accent-${accent}${p.recommended ? " recommended" : ""}${isChosen ? " chosen" : ""}`}
                  >
                    <div className="pw-path-head">
                      <span className="pw-path-pct">{pct(p.probability)}</span>
                      <span className="pw-path-label">{p.label}</span>
                      {p.recommended && <span className="pw-badge">Recommended</span>}
                    </div>
                    <div className="pw-path-steps">
                      {p.steps.map((s, i) => (
                        <span key={i} className={`pw-step-chip d-${s.decision}`}>
                          {titleFor(s.scenario_id).split(" — ")[0].slice(0, 26)} · {DECISION_LABEL[s.decision] ?? s.decision}
                        </span>
                      ))}
                    </div>
                    <button
                      className="pw-approve"
                      type="button"
                      disabled={status !== "planned" || approving}
                      onClick={() => onApprove(p.path_id)}
                    >
                      {isChosen ? "✓ Approved — executing" : "Approve this pathway"}
                    </button>
                  </div>
                );
              })}
              {paths.length === 0 && <div className="pw-paths-empty">No actionable pathways.</div>}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
