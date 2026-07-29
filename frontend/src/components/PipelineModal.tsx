/**
 * Full-screen pathway modal for a multi-scenario question.
 *
 * Shows the compose-then-branch graph plus the actionable VIABLE PATHWAYS the
 * reviewer can approve (most-probable tagged "Recommended"). Approving one
 * pathway executes it end-to-end (the backend auto-applies that path's
 * decisions and fires each step's action). Live progress overlays the actual
 * path onto the graph.
 */
import { useEffect, useMemo, useState } from "react";

import * as api from "../api";
import { PipelineForecast, PipelineState, ViablePath } from "../types";
import { OutcomeTreeGraph, OUTCOME_ACCENT, pct } from "./OutcomeTreeGraph";

const DECISION_LABEL: Record<string, string> = {
  approve: "approve",
  auto_execute: "auto-execute",
  reject: "reject",
  request_more_info: "more info",
};

// Distinct colours assigned to each scenario in the pipeline (used both to
// band the graph nodes and as the legend swatches).
const SCENARIO_PALETTE = ["#0d6e7f", "#a16207", "#7c3aed", "#0e7490", "#b45309", "#4d7c0f"];

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

  // Stable per-scenario colour map (scenarios don't change during a run).
  const scenarioIds = useMemo(
    () => [...new Set(pipeline.steps.map((s) => s.scenario_id))],
    [pipeline.pipeline_id] // eslint-disable-line react-hooks/exhaustive-deps
  );
  const scenarioColors = useMemo(
    () => Object.fromEntries(scenarioIds.map((id, i) => [id, SCENARIO_PALETTE[i % SCENARIO_PALETTE.length]])),
    [scenarioIds]
  );

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
          <div className="pw-left">
            <div className="pw-graph">
              <OutcomeTreeGraph
                plan={plan}
                actualPath={pstate?.actual_path}
                activeScenarioId={activeScenarioId}
                runActive={status === "running"}
                hideOutcomes
                scenarioColors={scenarioColors}
              />
            </div>
            <ScenarioLegend scenarioIds={scenarioIds} colors={scenarioColors} titleFor={titleFor} />
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
                      {!isChosen
                        ? "Approve this pathway"
                        : status === "complete"
                        ? "✓ Executed"
                        : status === "error"
                        ? "✗ Execution failed"
                        : status === "running"
                        ? "✓ Approved — executing…"
                        : "✓ Approved"}
                    </button>
                  </div>
                );
              })}
              {paths.length === 0 && <div className="pw-paths-empty">No actionable pathways.</div>}
            </div>
          </aside>
        </div>

        {status === "complete" && (
          <div className="pw-footer">
            <span className="pw-footer-msg">
              ✓ The pathway executed end-to-end (ended on <strong>{pstate?.terminal_decision ?? "—"}</strong>). Each step's action fired and is on the audit trail.
            </span>
            <button className="pw-done" type="button" onClick={onClose}>
              View outcome &amp; audit ▸
            </button>
          </div>
        )}
        {status === "error" && (
          <div className="pw-footer error">
            <span className="pw-footer-msg">Execution error: {pstate?.error ?? "unknown"}</span>
            <button className="pw-done" type="button" onClick={onClose}>Close</button>
          </div>
        )}
      </div>
    </div>
  );
}

/** Legend under the graph — colour swatch per scenario, click to drill into
 *  the scenario's ontology bindings + attributes. */
function ScenarioLegend({
  scenarioIds,
  colors,
  titleFor,
}: {
  scenarioIds: string[];
  colors: Record<string, string>;
  titleFor: (sid: string) => string;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [specs, setSpecs] = useState<Record<string, any>>({});

  const toggle = async (id: string) => {
    if (open === id) { setOpen(null); return; }
    setOpen(id);
    if (!specs[id]) {
      try {
        const s = await api.getScenarioSpec(id);
        setSpecs((prev) => ({ ...prev, [id]: s }));
      } catch { /* ignore */ }
    }
  };

  return (
    <div className="pw-legend">
      <div className="pw-legend-title">Scenarios in this question · click to drill in</div>
      <div className="pw-legend-items">
        {scenarioIds.map((id) => (
          <div key={id} className="pw-legend-item">
            <button className={`pw-legend-chip${open === id ? " active" : ""}`} type="button" onClick={() => toggle(id)}>
              <span className="pw-legend-swatch" style={{ background: colors[id] }} />
              <span className="pw-legend-name">{titleFor(id).split(" — ")[0]}</span>
              <span className="pw-legend-caret">{open === id ? "▾" : "▸"}</span>
            </button>
            {open === id && <ScenarioDetail id={id} spec={specs[id]} />}
          </div>
        ))}
      </div>
    </div>
  );
}

function ScenarioDetail({ id, spec }: { id: string; spec: any }) {
  if (!spec) return <div className="pw-legend-detail">Loading {id}…</div>;
  const stages: Record<string, any> = spec.stages || {};
  const bindings: { ontology: string; cls: string; purpose: string }[] = [];
  for (const stage of Object.values(stages)) {
    for (const q of (stage?.ontology_queries || [])) {
      bindings.push({ ontology: q.ontology, cls: q.class, purpose: q.purpose || "" });
    }
  }
  const facts = (stages.agent_intake?.facts || []).map((f: any) => ({ type: f.ontology_type, title: f.title }));
  const outcomes = Object.keys(spec.outcomes || {});

  return (
    <div className="pw-legend-detail">
      <div className="pw-legend-row">
        <b>Domain:</b> {spec.domain || "—"}
        {spec.autonomous && <span className="pw-badge">autonomous</span>}
        {spec.risk_bands && <span className="pw-badge">risk bands</span>}
      </div>
      {spec.action_type && <div className="pw-legend-row"><b>Action:</b> <code>{spec.action_type}</code></div>}
      {bindings.length > 0 && (
        <>
          <div className="pw-legend-sub">Ontology bindings ({bindings.length})</div>
          {bindings.map((b, i) => (
            <div key={i} className="pw-legend-binding">
              <code>{b.ontology}.{b.cls}</code>
              {b.purpose && <span className="pw-legend-purpose"> — {b.purpose.slice(0, 90)}</span>}
            </div>
          ))}
        </>
      )}
      {facts.length > 0 && (
        <>
          <div className="pw-legend-sub">Bound attributes / facts</div>
          {facts.map((f: any, i: number) => (
            <div key={i} className="pw-legend-binding"><code>{f.type}</code> {f.title}</div>
          ))}
        </>
      )}
      {outcomes.length > 0 && <div className="pw-legend-row"><b>Outcomes:</b> {outcomes.join(", ")}</div>}
    </div>
  );
}
