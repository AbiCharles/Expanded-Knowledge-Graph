/**
 * Phase 3a — pattern-mining insight viewer.
 *
 * Admin-only. Aggregates the per-case load-bearing-fact captures from
 * Phase 2 and shows recurring drivers per scenario. Phase 3b will add
 * a "promote this pattern" admin flow on top of the same data.
 *
 * Launched from the StatusBar (next to the Metrics button).
 */
import { useEffect, useState } from "react";
import * as api from "../api";

const DECISION_LABEL: Record<string, string> = {
  approve: "Approve",
  reject: "Reject",
  request_more_info: "Request more info",
};

const DECISION_CLASS: Record<string, string> = {
  approve: "insights-decision approve",
  reject: "insights-decision reject",
  request_more_info: "insights-decision info",
};


export function InsightsModal({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<api.PatternsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getInsightsPatterns()
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError((e as Error).message); });
    return () => { cancelled = true; };
  }, []);

  // Esc closes the modal.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="ds-modal insights-modal" style={{ maxWidth: 920, width: "92vw" }}>
        <div className="ds-header">
          <div>
            <div className="ds-eyebrow">Phase 3 · Pattern insights</div>
            <div className="ds-title">Recurring override drivers</div>
          </div>
          <button className="teams-close" onClick={onClose}>×</button>
        </div>

        <div className="insights-body">
          <p className="insights-intro">
            Each row is a fact type the reviewer flagged as load-bearing
            when reaching a decision. <strong>Share of decision</strong>{" "}
            tells you how often this driver was cited when the reviewer
            picked that outcome. Phase 3 will use these patterns to
            propose new scenario versions automatically.
          </p>

          {error && <div className="ds-error">{error}</div>}
          {!data && !error && <div className="insights-loading">Loading…</div>}

          {data && data.scenarios.length === 0 && (
            <div className="insights-empty">
              No reviewer signal yet. Cases will populate this view as
              reviewers flag load-bearing facts during decisions.
            </div>
          )}

          {data && data.scenarios.map((s) => (
            <div className="insights-scenario" key={s.scenario_id}>
              <div className="insights-scenario-head">
                <span className="insights-scenario-id">{s.scenario_id}</span>
                <span className="insights-scenario-meta">
                  {s.total_decided_cases} decided case{s.total_decided_cases === 1 ? "" : "s"}
                </span>
              </div>
              <table className="insights-table">
                <thead>
                  <tr>
                    <th>Decision</th>
                    <th>Driver (ontology type)</th>
                    <th>Cases</th>
                    <th>Share of decision</th>
                    <th>Share of all</th>
                    <th>Sample fact ids</th>
                  </tr>
                </thead>
                <tbody>
                  {s.patterns.map((p, i) => (
                    <tr key={`${p.decision_kind}|${p.fact_ontology_type}|${i}`}>
                      <td>
                        <span className={DECISION_CLASS[p.decision_kind] || "insights-decision"}>
                          {DECISION_LABEL[p.decision_kind] || p.decision_kind}
                        </span>
                      </td>
                      <td><span className="insights-ot">{p.fact_ontology_type}</span></td>
                      <td className="insights-num">{p.case_count}</td>
                      <td className="insights-num">{p.share_of_decision_kind}%</td>
                      <td className="insights-num">{p.share_of_decisions}%</td>
                      <td className="insights-samples">
                        {p.sample_fact_ids.length === 0 ? <span className="insights-meta">—</span> : p.sample_fact_ids.join(", ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
