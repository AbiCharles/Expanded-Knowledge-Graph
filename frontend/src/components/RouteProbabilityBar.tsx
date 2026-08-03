/**
 * The answer-strategy router's 3-way A/B/C probability bar + legend.
 *
 * Shown the instant a question is classified: what each strategy means, how
 * likely each is the right way to answer, which one was chosen (the highest
 * probability runs), and the expected correctness of that answer. Mirrors
 * backend RouteResult (backend/agent_runtime.py).
 */
import { Routing, RouteStrategy } from "../types";

const STRATEGY: Record<
  RouteStrategy,
  { label: string; short: string; color: string; blurb: string; reliability: string }
> = {
  single: {
    label: "Single scenario",
    short: "A",
    color: "#0d9488",
    blurb: "One governed scenario answers it directly — it may still need review or a live data pull.",
    reliability: "Most reliable",
  },
  pipeline: {
    label: "Multiple scenarios",
    short: "B",
    color: "#7c3aed",
    blurb: "Several governed scenarios stitched into a pipeline; can have several outcomes.",
    reliability: "Usually reliable",
  },
  rag: {
    label: "RAG / generative",
    short: "C",
    color: "#b45309",
    blurb: "No scenario matches — retrieval + generation over the policy corpus (or general knowledge).",
    reliability: "Least deterministic",
  },
};

const ORDER: RouteStrategy[] = ["single", "pipeline", "rag"];
const pct = (x: number) => `${Math.round(x * 100)}%`;

export function RouteProbabilityBar({ routing }: { routing: Routing }) {
  const probOf = (k: RouteStrategy) =>
    k === "single" ? routing.p_a : k === "pipeline" ? routing.p_b : routing.p_c;

  return (
    <section className="route-bar" aria-label="Answer-strategy routing">
      <div className="route-head">
        <span className="route-eyebrow">How this question is being answered</span>
        <span
          className="route-conf"
          title="Expected correctness of the chosen answer — A weighted highest, C lowest"
        >
          Expected correctness <strong>{pct(routing.confidence)}</strong>
        </span>
      </div>

      {/* Stacked distribution — the whole probability mass across A/B/C. */}
      <div className="route-track" role="img" aria-label="Strategy probability distribution">
        {ORDER.map((k) => (
          <div
            key={k}
            className={`route-seg${routing.strategy === k ? " chosen" : ""}`}
            style={{ width: probOf(k) <= 0.005 ? "0%" : `${Math.max(probOf(k) * 100, 2)}%`, background: STRATEGY[k].color }}
            title={`${STRATEGY[k].label} · ${pct(probOf(k))}`}
          >
            {probOf(k) >= 0.12 && (
              <span className="route-seg-label">
                {STRATEGY[k].short} {pct(probOf(k))}
              </span>
            )}
          </div>
        ))}
      </div>

      {/* Explanatory legend — what each strategy is + how likely it is here. */}
      <div className="route-items">
        {ORDER.map((k) => {
          const meta = STRATEGY[k];
          const chosen = routing.strategy === k;
          return (
            <div key={k} className={`route-item${chosen ? " chosen" : ""}`}>
              <span className="route-badge" style={{ background: meta.color }}>{meta.short}</span>
              <div className="route-item-body">
                <div className="route-item-top">
                  <span className="route-item-name">{meta.label}</span>
                  {chosen && <span className="route-chosen-tag">✓ chosen</span>}
                  <span className="route-item-reliab">{meta.reliability}</span>
                  <span className="route-item-pct">{pct(probOf(k))}</span>
                </div>
                <div className="route-item-blurb">{meta.blurb}</div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="route-foot">
        The highest-probability strategy runs — <strong>{STRATEGY[routing.strategy].label}</strong> here.
        {routing.rationale ? ` ${routing.rationale}` : ""} RAG is used only when no scenario
        matches. The meter weights A → B → C by reliability, so more mass on A means a more
        trustworthy answer.
      </div>
    </section>
  );
}
