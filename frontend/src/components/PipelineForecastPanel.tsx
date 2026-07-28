/**
 * Auto-shown when a user's question is detected to span multiple scenarios.
 *
 * Renders the planned scenario pipeline (ordered steps) and the projected
 * probability-weighted Outcome DAG (the "forecast" from POST /api/cases).
 * This is the question-driven counterpart to OutcomeTreeModal's manual
 * multi-select. Phase 2 will overlay the live actual-path as the real
 * chained execution runs.
 */
import { PipelineForecast } from "../types";
import { OutcomeTreeGraph } from "./OutcomeTreeGraph";

export function PipelineForecastPanel({
  pipeline,
  onClose,
}: {
  pipeline: PipelineForecast;
  onClose?: () => void;
}) {
  return (
    <section className="pipeline-panel" aria-label="Projected outcome pathways">
      <div className="pipeline-head">
        <span className="pipeline-eyebrow">Multi-scenario question</span>
        <h3>Projected outcome pathways</h3>
        {pipeline.rationale && <p>{pipeline.rationale}</p>}
        {onClose && (
          <button className="pipeline-close" type="button" onClick={onClose} aria-label="Dismiss">×</button>
        )}
      </div>

      <ol className="pipeline-steps">
        {pipeline.steps.map((s, i) => (
          <li key={s.scenario_id} title={s.why || s.scenario_id}>
            {i > 0 && <span className="pipeline-step-arrow">→</span>}
            <span className="pipeline-step-n">{i + 1}</span>
            <span className="pipeline-step-title">{s.title}</span>
            {s.why && <span className="pipeline-step-why">{s.why}</span>}
          </li>
        ))}
      </ol>

      <div className="pipeline-graph">
        <OutcomeTreeGraph plan={pipeline.forecast} />
      </div>
    </section>
  );
}
