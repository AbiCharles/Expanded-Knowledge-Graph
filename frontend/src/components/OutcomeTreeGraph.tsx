/**
 * Reusable probability-weighted Outcome DAG renderer (Cytoscape + dagre).
 *
 * Given an OutcomePlan (from POST /api/graph/outcome-tree or the pipeline
 * forecast on POST /api/cases), draws the compose-then-branch graph and a
 * ranked-outcomes panel. Clicking an outcome highlights the most-probable
 * path to it via a probability-weighted Dijkstra (edge cost = −log p, so the
 * shortest path maximises the product of branch probabilities).
 *
 * Used by OutcomeTreeModal (manual multi-select) and PipelineForecastPanel
 * (auto-detected multi-scenario questions).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import CytoscapeComponent from "react-cytoscapejs";
import cytoscape from "cytoscape";
import dagre from "cytoscape-dagre";

import { OutcomePlan, OutcomeSummary } from "../types";

// Register the dagre layout once (Cytoscape throws on double-registration).
try { cytoscape.use(dagre); } catch { /* already registered */ }

// react-cytoscapejs re-runs any non-preset layout on every prop change; pin
// to preset and drive dagre ourselves so node positions never get clobbered.
const PRESET_LAYOUT = { name: "preset" } as const;

// Outcome-kind → accent class (matches the palette language in GraphViz).
export const OUTCOME_ACCENT: Record<string, string> = {
  approve: "good",
  auto_execute: "good",
  reject: "risk",
  request_more_info: "warn",
  review_ready: "alt",
};

const BASIS_LABEL: Record<string, string> = {
  author: "author-set",
  history: "from history",
  default: "prior",
  agent: "agent",
  structural: "",
};

export function pct(p: number | null | undefined): string {
  if (p == null) return "";
  return `${(p * 100).toFixed(p >= 0.1 ? 0 : 1)}%`;
}

function toElements(plan: OutcomePlan): any[] {
  const els: any[] = [];
  for (const n of plan.nodes) {
    const accent =
      n.kind === "outcome"
        ? OUTCOME_ACCENT[n.outcome_kind || ""] || "alt"
        : n.accent || "default";
    const label =
      n.kind === "outcome" && n.probability != null
        ? `${n.label}\n(${pct(n.probability)})`
        : n.label;
    els.push({
      data: { id: n.id, label, kind: n.kind, accent, prob: n.probability ?? null },
      classes: `otree-node kind-${n.kind} accent-${accent}`,
    });
  }
  for (const e of plan.edges) {
    const basis = BASIS_LABEL[e.basis] ?? e.basis;
    const showProb = e.label !== "start" && e.label !== "proposal";
    const label = showProb
      ? `${pct(e.probability)}${basis ? ` · ${basis}` : ""}`
      : "";
    els.push({
      data: {
        id: e.id,
        source: e.source,
        target: e.target,
        label,
        prob: e.probability,
        basis: e.basis,
      },
      classes: `otree-edge basis-${e.basis} accent-${e.accent || "none"}`,
    });
  }
  return els;
}

const STYLESHEET: any[] = [
  {
    selector: "node.otree-node",
    style: {
      label: "data(label)",
      "text-wrap": "wrap",
      "text-max-width": 120,
      "font-family": "Fraunces, Georgia, serif",
      "font-size": 8,
      color: "#0f172a",
      "text-valign": "center",
      "text-halign": "center",
      "background-color": "#94a3b8",
      "border-width": 1.5,
      "border-color": "rgba(15,23,42,0.2)",
      width: 26,
      height: 26,
      "min-zoomed-font-size": 5,
    },
  },
  {
    selector: "node.kind-question",
    style: {
      shape: "round-rectangle",
      "background-color": "#0d6e7f",
      "border-color": "#0a4f5c",
      color: "#ffffff",
      "font-weight": 600,
      "font-size": 9,
      "text-valign": "center",
      width: "label",
      height: "label",
      padding: 10,
      "text-max-width": 150,
    },
  },
  {
    selector: "node.kind-scenario_step",
    style: {
      shape: "round-rectangle",
      "background-color": "#e2e8f0",
      "border-color": "#94a3b8",
      color: "#1e293b",
      width: "label",
      height: "label",
      padding: 9,
      "font-weight": 600,
      "text-max-width": 150,
    },
  },
  {
    selector: "node.kind-decision",
    style: {
      shape: "diamond",
      "background-color": "#d4a93a",
      "border-color": "#8a6d20",
      color: "#4a3a10",
      width: 34,
      height: 34,
    },
  },
  {
    selector: "node.kind-outcome",
    style: {
      shape: "round-rectangle",
      width: "label",
      height: "label",
      padding: 8,
      "font-weight": 600,
      "text-max-width": 130,
    },
  },
  { selector: "node.kind-outcome.accent-good", style: { "background-color": "#3f9d6d", "border-color": "#1f6e46", color: "#0c3d24" } },
  { selector: "node.kind-outcome.accent-risk", style: { "background-color": "#c14a4a", "border-color": "#7a2424", color: "#3a0f0f" } },
  { selector: "node.kind-outcome.accent-warn", style: { "background-color": "#d99a2b", "border-color": "#8a6215", color: "#3f2c07" } },
  { selector: "node.kind-outcome.accent-alt", style: { "background-color": "#8592a6", "border-color": "#4a5568", color: "#1f2733" } },
  {
    selector: "edge.otree-edge",
    style: {
      "curve-style": "bezier",
      "target-arrow-shape": "triangle",
      "line-color": "#cbd5e1",
      "target-arrow-color": "#cbd5e1",
      width: "mapData(prob, 0, 1, 1.2, 6)",
      label: "data(label)",
      "font-family": "ui-sans-serif, system-ui, sans-serif",
      "font-size": 7,
      color: "#475569",
      "text-background-color": "#ffffff",
      "text-background-opacity": 0.85,
      "text-background-padding": 2,
      "min-zoomed-font-size": 6,
    },
  },
  { selector: "edge.basis-author", style: { "line-color": "#8b8ad6", "target-arrow-color": "#8b8ad6", color: "#4f46e5" } },
  {
    selector: ".otree-hl",
    style: {
      "line-color": "#4f46e5",
      "target-arrow-color": "#4f46e5",
      "border-color": "#4f46e5",
      "border-width": 3,
      color: "#312e81",
      "z-index": 20,
    },
  },
  { selector: "node.otree-hl", style: { "border-width": 3, "border-color": "#4f46e5" } },
  { selector: ".otree-dim", style: { opacity: 0.22 } },
];

const DAGRE = { name: "dagre", rankDir: "LR", nodeSep: 40, rankSep: 90, edgeSep: 16, padding: 24, animate: false };

export function OutcomeTreeGraph({
  plan,
  emptyHint,
}: {
  plan: OutcomePlan | null;
  emptyHint?: string;
}) {
  const [selectedOutcome, setSelectedOutcome] = useState<string | null>(null);
  const cyRef = useRef<any>(null);
  const [cyTick, setCyTick] = useState(0);

  const elements = useMemo(() => (plan ? toElements(plan) : []), [plan]);

  // Reset selection to the most-probable outcome whenever the plan changes.
  useEffect(() => {
    setSelectedOutcome(plan?.outcomes[0]?.id ?? null);
  }, [plan]);

  // Run dagre once cy has the new elements attached.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || elements.length === 0) return;
    try {
      const l = cy.layout(DAGRE);
      l.on("layoutstop", () => { try { cy.fit(undefined, 30); } catch { /* noop */ } });
      l.run();
      setTimeout(() => { try { cy.fit(undefined, 30); } catch { /* noop */ } }, 250);
    } catch { /* noop */ }
  }, [elements, cyTick]);

  // Highlight the most-probable path to the selected outcome (weighted Dijkstra).
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !plan) return;
    cy.batch(() => {
      cy.elements().removeClass("otree-hl otree-dim");
      if (!selectedOutcome) return;
      const root = plan.nodes.find((n) => n.kind === "question");
      const target = cy.getElementById(selectedOutcome);
      if (!root || target.empty()) return;
      const rootNode = cy.getElementById(root.id);
      if (rootNode.empty()) return;
      const dijkstra = cy.elements().dijkstra({
        root: rootNode,
        weight: (edge: any) => -Math.log(Math.max(edge.data("prob") ?? 1e-6, 1e-6)),
        directed: true,
      });
      const path = dijkstra.pathTo(target);
      if (path.length > 0) {
        cy.elements().addClass("otree-dim");
        path.removeClass("otree-dim").addClass("otree-hl");
      }
    });
  }, [plan, selectedOutcome, cyTick]);

  if (!plan) {
    return (
      <div className="otree-graph">
        <div className="otree-canvas">
          <div className="otree-empty">{emptyHint ?? "No outcome graph yet."}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="otree-graph">
      <div className="otree-canvas">
        <CytoscapeComponent
          elements={elements}
          layout={PRESET_LAYOUT}
          stylesheet={STYLESHEET}
          style={{ width: "100%", height: "100%" }}
          wheelSensitivity={0.2}
          cy={(cy: any) => {
            if (cyRef.current === cy) return;
            cyRef.current = cy;
            cy.maxZoom(1.5);
            cy.minZoom(0.2);
            cy.on("tap", "node.kind-outcome", (evt: any) => setSelectedOutcome(evt.target.id()));
            setCyTick((n) => n + 1);
          }}
        />
      </div>
      <aside className="otree-outcomes">
        <div className="otree-outcomes-head">
          Outcomes <span>({plan.outcomes.length})</span>
        </div>
        <div className="otree-outcomes-stats">
          {plan.stats.paths} paths · total {pct(plan.stats.total_probability)}
        </div>
        <div className="otree-outcomes-list">
          {plan.outcomes.map((o: OutcomeSummary) => {
            const accent = OUTCOME_ACCENT[o.outcome_kind || ""] || "alt";
            return (
              <button
                key={o.id}
                type="button"
                className={`otree-outcome accent-${accent}${selectedOutcome === o.id ? " active" : ""}`}
                onClick={() => setSelectedOutcome(o.id)}
              >
                <div className="otree-outcome-bar">
                  <div className="otree-outcome-fill" style={{ width: `${Math.max(3, o.probability * 100)}%` }} />
                </div>
                <div className="otree-outcome-row">
                  <span className="otree-outcome-pct">{pct(o.probability)}</span>
                  <span className="otree-outcome-label">{o.label}</span>
                </div>
                {o.scenario_id && <div className="otree-outcome-scn">{o.scenario_id}</div>}
              </button>
            );
          })}
        </div>
      </aside>
    </div>
  );
}
