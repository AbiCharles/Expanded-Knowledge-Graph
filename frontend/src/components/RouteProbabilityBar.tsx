/**
 * The answer-strategy router's 3-way A/B/C probability bar.
 *
 * Shown the instant a question is classified: how likely each answer strategy
 * is the right one (deterministic single scenario / multi-scenario pipeline /
 * RAG-generative), which one was chosen, and the expected correctness of that
 * answer. Mirrors backend RouteResult (backend/agent_runtime.py).
 */
import { Routing, RouteStrategy } from "../types";

const STRATEGY: Record<RouteStrategy, { label: string; short: string; color: string }> = {
  deterministic: { label: "Deterministic scenario", short: "A", color: "#0d9488" },
  pipeline: { label: "Multi-scenario pipeline", short: "B", color: "#7c3aed" },
  rag: { label: "RAG / generative", short: "C", color: "#b45309" },
};

const pct = (x: number) => `${Math.round(x * 100)}%`;

export function RouteProbabilityBar({ routing }: { routing: Routing }) {
  const segments: { key: RouteStrategy; p: number }[] = [
    { key: "deterministic", p: routing.p_a },
    { key: "pipeline", p: routing.p_b },
    { key: "rag", p: routing.p_c },
  ];

  return (
    <section className="route-bar" aria-label="Answer-strategy routing">
      <div className="route-head">
        <span className="route-eyebrow">How this question is being answered</span>
        <span className="route-conf" title="Expected correctness of the chosen answer">
          Confidence <strong>{pct(routing.confidence)}</strong>
        </span>
      </div>

      <div className="route-track" role="img" aria-label="Strategy probability distribution">
        {segments.map((s) => (
          <div
            key={s.key}
            className={`route-seg${routing.strategy === s.key ? " chosen" : ""}`}
            style={{ width: `${Math.max(s.p * 100, 2)}%`, background: STRATEGY[s.key].color }}
            title={`${STRATEGY[s.key].label} · ${pct(s.p)}`}
          >
            {s.p >= 0.12 && (
              <span className="route-seg-label">
                {STRATEGY[s.key].short} {pct(s.p)}
              </span>
            )}
          </div>
        ))}
      </div>

      <div className="route-legend">
        {segments.map((s) => (
          <span key={s.key} className={`route-key${routing.strategy === s.key ? " chosen" : ""}`}>
            <i style={{ background: STRATEGY[s.key].color }} aria-hidden="true" />
            {STRATEGY[s.key].label} · {pct(s.p)}
          </span>
        ))}
      </div>

      <div className="route-chosen">
        <strong>{STRATEGY[routing.strategy].label}</strong> chosen — {routing.rationale}
      </div>
    </section>
  );
}
