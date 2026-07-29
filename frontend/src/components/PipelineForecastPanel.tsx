/**
 * Auto-shown when a user's question is detected to span multiple scenarios.
 *
 * Renders the planned scenario pipeline and the projected probability-weighted
 * Outcome DAG. "Run pipeline" (Phase 2) kicks off the real chained HITL
 * execution: each step is reviewed through the normal case UI, and this panel
 * polls pipeline state, advances the active case, and overlays the actual
 * path taken onto the forecast graph as it happens.
 */
import { useEffect, useRef, useState } from "react";

import * as api from "../api";
import { PipelineForecast, PipelineState } from "../types";
import { OutcomeTreeGraph } from "./OutcomeTreeGraph";

const DECISION_MARK: Record<string, { icon: string; cls: string }> = {
  approve: { icon: "✓", cls: "good" },
  auto_execute: { icon: "⚡", cls: "good" },
  reject: { icon: "✗", cls: "risk" },
  request_more_info: { icon: "?", cls: "warn" },
};

export function PipelineForecastPanel({
  pipeline,
  onClose,
  onActiveCase,
}: {
  pipeline: PipelineForecast;
  onClose?: () => void;
  onActiveCase?: (caseId: string) => void;
}) {
  const [pstate, setPstate] = useState<PipelineState | null>(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<number | undefined>(undefined);
  const lastActiveCase = useRef<string | null>(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = undefined;
    }
  };
  useEffect(() => stopPolling, []);

  // A new pipeline (different question) resets local state.
  useEffect(() => {
    stopPolling();
    setPstate(null);
    setBusy(false);
    lastActiveCase.current = null;
  }, [pipeline.pipeline_id]);

  const poll = async () => {
    try {
      const p = await api.getPipeline(pipeline.pipeline_id);
      setPstate(p);
      const cur = p.steps[p.current_step];
      if (cur?.case_id && cur.case_id !== lastActiveCase.current) {
        lastActiveCase.current = cur.case_id;
        onActiveCase?.(cur.case_id);
      }
      if (p.status === "complete" || p.status === "error") {
        stopPolling();
        setBusy(false);
      }
    } catch {
      /* transient; keep polling */
    }
  };

  const run = async () => {
    setBusy(true);
    try {
      await api.confirmPipeline(pipeline.pipeline_id);
      stopPolling();
      poll();
      pollRef.current = window.setInterval(poll, 1200);
    } catch (e) {
      setBusy(false);
      alert((e as Error).message);
    }
  };

  const status = pstate?.status ?? "planned";
  const steps = pstate?.steps ?? pipeline.steps.map((s) => ({ ...s, case_id: null, decision: null as string | null }));
  const activeScenarioId =
    status === "running" && pstate ? pstate.steps[pstate.current_step]?.scenario_id ?? null : null;
  const plan = pstate?.forecast ?? pipeline.forecast;

  return (
    <section className="pipeline-panel" aria-label="Projected outcome pathways">
      <div className="pipeline-head">
        <span className="pipeline-eyebrow">Multi-scenario question</span>
        <h3>{status === "planned" ? "Projected outcome pathways" : "Pipeline run"}</h3>
        {pipeline.rationale && <p>{pipeline.rationale}</p>}
        {onClose && (
          <button className="pipeline-close" type="button" onClick={onClose} aria-label="Dismiss">×</button>
        )}
      </div>

      <div className="pipeline-controls">
        <ol className="pipeline-steps">
          {steps.map((s, i) => {
            const mark = s.decision ? DECISION_MARK[s.decision] : null;
            const isCurrent = status === "running" && pstate?.current_step === i && !s.decision;
            return (
              <li key={`${s.scenario_id}-${i}`} title={s.why || s.scenario_id} className={isCurrent ? "current" : ""}>
                {i > 0 && <span className="pipeline-step-arrow">→</span>}
                <span className={`pipeline-step-n${mark ? ` ${mark.cls}` : ""}${isCurrent ? " current" : ""}`}>
                  {mark ? mark.icon : i + 1}
                </span>
                <span className="pipeline-step-title">{s.title}</span>
              </li>
            );
          })}
        </ol>
        {status === "planned" && (
          <button className="pipeline-run" type="button" onClick={run} disabled={busy}>
            {busy ? "Starting…" : "▶ Run pipeline"}
          </button>
        )}
        {status === "running" && <span className="pipeline-status running">Running · step {(pstate?.current_step ?? 0) + 1}…</span>}
        {status === "complete" && (
          <span className="pipeline-status complete">
            Complete · ended on {pstate?.terminal_decision ?? "—"}
          </span>
        )}
        {status === "error" && <span className="pipeline-status error">Error: {pstate?.error}</span>}
      </div>

      <div className="pipeline-graph">
        <OutcomeTreeGraph plan={plan} actualPath={pstate?.actual_path} activeScenarioId={activeScenarioId} />
      </div>
    </section>
  );
}
