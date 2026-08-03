/**
 * Multi-scenario Outcome DAG viewer (manual multi-select).
 *
 * Lets an operator hand-pick several scenarios to answer one complex
 * question ("compose then branch"), then renders the resulting
 * probability-weighted outcome graph via the shared OutcomeTreeGraph.
 * (The automatic, question-driven path is PipelineForecastPanel.)
 *
 * Backend: POST /api/graph/outcome-tree (backend/scenario_composer.py).
 * Launched from the StatusBar.
 */
import { useEffect, useState } from "react";

import * as api from "../api";
import { OutcomePlan, ScenarioRow } from "../types";
import { OutcomeTreeGraph, pct } from "./OutcomeTreeGraph";

export function OutcomeTreeModal({
  scenarios,
  onClose,
}: {
  scenarios: ScenarioRow[];
  onClose: () => void;
}) {
  const [question, setQuestion] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [useReliability, setUseReliability] = useState(false);
  const [reliability, setReliability] = useState(0.7);
  const [filter, setFilter] = useState("");
  const [plan, setPlan] = useState<OutcomePlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Esc closes.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const toggle = (id: string) =>
    setSelected((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));

  async function compose() {
    if (!question.trim() || selected.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const ctx = useReliability ? { reliability_score: reliability } : {};
      setPlan(await api.outcomeTree(question.trim(), selected, ctx));
    } catch (e) {
      setError((e as Error).message);
      setPlan(null);
    } finally {
      setLoading(false);
    }
  }

  const shown = scenarios.filter(
    (s) =>
      !filter ||
      s.title.toLowerCase().includes(filter.toLowerCase()) ||
      s.id.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="ds-modal otree-modal" style={{ maxWidth: 1180, width: "94vw", height: "88vh" }}>
        <div className="ds-header">
          <div>
            <div className="ds-eyebrow">Multi-scenario reasoning</div>
            <h2 className="ds-title">Outcome pathways</h2>
            <p className="ds-sub">
              Stitch scenarios into one answer and see every outcome, the paths to it, and how likely each is.
            </p>
          </div>
          <button className="graph-modal-close" type="button" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="otree-body">
          {/* Config rail */}
          <aside className="otree-config">
            <label className="otree-label">Question</label>
            <textarea
              className="otree-question"
              rows={3}
              placeholder="e.g. If our tier-2 supplier fails, what happens to the auto-release?"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />

            <label className="otree-label">
              Scenarios to stitch <span className="otree-hint">(click in pipeline order)</span>
            </label>
            <input
              className="otree-filter"
              placeholder="Filter scenarios…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <div className="otree-scenario-list">
              {shown.map((s) => {
                const order = selected.indexOf(s.id);
                return (
                  <button
                    key={s.id}
                    type="button"
                    className={`otree-scenario${order >= 0 ? " selected" : ""}`}
                    onClick={() => toggle(s.id)}
                    title={s.id}
                  >
                    <span className="otree-scenario-order">{order >= 0 ? order + 1 : ""}</span>
                    <span className="otree-scenario-title">{s.title}</span>
                    {s.autonomous && <span className="otree-badge">auto</span>}
                  </button>
                );
              })}
            </div>

            <label className="otree-reliability">
              <input
                type="checkbox"
                checked={useReliability}
                onChange={(e) => setUseReliability(e.target.checked)}
              />
              Supplier reliability signal
            </label>
            {useReliability && (
              <div className="otree-slider-row">
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={reliability}
                  onChange={(e) => setReliability(Number(e.target.value))}
                />
                <span>{pct(reliability)}</span>
              </div>
            )}

            <button
              className="otree-compose"
              type="button"
              onClick={compose}
              disabled={loading || !question.trim() || selected.length === 0}
            >
              {loading ? "Composing…" : `Compose ${selected.length || ""} scenario${selected.length === 1 ? "" : "s"}`}
            </button>
            {error && <div className="otree-error">{error}</div>}
          </aside>

          {/* Graph + ranked outcomes */}
          <OutcomeTreeGraph
            plan={plan}
            emptyHint={
              loading
                ? "Composing…"
                : "Pick one or more scenarios, ask a question, and compose to see the outcome graph."
            }
          />
        </div>
      </div>
    </div>
  );
}
