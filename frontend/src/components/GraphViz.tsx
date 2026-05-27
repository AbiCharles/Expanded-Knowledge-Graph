import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import cytoscape from "cytoscape";
import dagre from "cytoscape-dagre";
import CytoscapeComponent from "react-cytoscapejs";

import { CaseFull } from "../types";
import {
  GraphNode as ApiNode,
  GraphEdge as ApiEdge,
  SubgraphResponse,
  getSupplierSubgraph,
} from "../api";
import {
  GraphFilterType,
  getHiddenGraphTypes,
  subscribeHiddenGraphTypes,
  nodeHiddenBy,
} from "../graphFilters";
import {
  DRILL_HANDLERS,
  DrillTarget,
  GraphAnchor,
  drillGlyphSvgUri,
  drillKindFor,
  findGraphAnchor,
} from "../graphDrill";

// Register the dagre layout once at module load — Cytoscape complains if
// the same layout is registered twice across hot-reloads, so guard.
try { cytoscape.use(dagre); } catch { /* already registered */ }

// Stable `preset` layout passed to CytoscapeComponent so the library
// never re-runs a layout on prop change. We run every layout from our
// own runLayout() helper instead.
const PRESET_LAYOUT = { name: "preset", fit: false } as const;

type LayoutName = "cose" | "dagre" | "breadthfirst" | "circle" | "grid";

interface CyElement {
  data: Record<string, unknown>;
  classes?: string;
}

// =============================================================================
// Inline preview panels — collapsible, embedded at the top of the envelope
// =============================================================================

// Lazy-fetches a Neo4j subgraph for the given supplier. Both GraphPanel
// (its standalone Knowledge-graph card) and the drill flow in
// EvidenceMap / PlatformFlowModal call this so they share the same
// loading + error state and avoid duplicating the round-trip when the
// reviewer drills into the same anchor twice.
function useSupplierSubgraph(supplier_id: string | null, active: boolean) {
  const [data, setData] = useState<SubgraphResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!active || !supplier_id) return;
    let cancelled = false;
    setError(null);
    getSupplierSubgraph(supplier_id)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError((e as Error).message); });
    return () => { cancelled = true; };
  }, [active, supplier_id]);

  return { data, error };
}

export function GraphPanel({ active }: { active: CaseFull }) {
  const anchor = useMemo(() => findGraphAnchor(active), [active]);
  const [modalOpen, setModalOpen] = useState(false);
  const hidden = useFilterSubscription();
  const { data, error } = useSupplierSubgraph(
    anchor?.supplier_id ?? null,
    modalOpen,
  );

  if (!anchor) return null;

  return (
    <>
      <button
        type="button"
        className="viz-card-button"
        onClick={() => setModalOpen(true)}
      >
        <span className="viz-card-eyebrow">Knowledge graph</span>
        <span className="viz-card-title">
          The supplier network around {anchor.supplierName} · {anchor.supplier_id}
        </span>
        <span className="viz-card-cta">Open in full-page graph &nbsp;⤢</span>
      </button>
      {modalOpen && (
        <GraphModal
          title="Knowledge graph"
          subtitle={`${anchor.supplier_id} · ${anchor.supplierName}`}
          rawNodes={data?.nodes}
          rawEdges={data?.edges}
          defaultLayout="dagre"
          onClose={() => setModalOpen(false)}
          loading={!data && !error}
          error={error}
          hidden={hidden}
        />
      )}
    </>
  );
}

export function EvidenceMap({ active }: { active: CaseFull }) {
  const [modalOpen, setModalOpen] = useState(false);
  const [drill, setDrill] = useState<DrillTarget | null>(null);
  const elements = useMemo(() => buildEvidenceElements(active), [active]);
  // Drill fetch — only fires when a knowledge-graph drill target lands.
  const drillAnchor = drill?.kind === "knowledge-graph" ? drill.anchor : null;
  const { data: drillData, error: drillError } = useSupplierSubgraph(
    drillAnchor?.supplier_id ?? null,
    !!drillAnchor,
  );
  if (!active.stages || active.stages.length === 0) return null;
  const totalFacts = active.stages.reduce((acc, s) => acc + s.facts.length, 0);
  const sourceKindCount = countSourceKinds(active);

  return (
    <>
      <button
        type="button"
        className="viz-card-button"
        onClick={() => setModalOpen(true)}
      >
        <span className="viz-card-eyebrow">Multi-source evidence map</span>
        <span className="viz-card-title">
          {totalFacts} fact{totalFacts === 1 ? "" : "s"} gathered from{" "}
          {sourceKindCount} system{sourceKindCount === 1 ? "" : "s"}
        </span>
        <span className="viz-card-cta">Open in full-page graph &nbsp;⤢</span>
      </button>
      {modalOpen && (
        <GraphModal
          title="Multi-source evidence map"
          subtitle="Prompt → stages → ontology classes → data sources → outcome"
          elements={elements}
          defaultLayout="dagre"
          onClose={() => setModalOpen(false)}
          hideFilters
          onDrill={setDrill}
          active={active}
        />
      )}
      {drillAnchor && (
        <GraphModal
          title="Knowledge graph"
          subtitle={`${drillAnchor.supplier_id} · ${drillAnchor.supplierName}`}
          rawNodes={drillData?.nodes}
          rawEdges={drillData?.edges}
          defaultLayout="dagre"
          onClose={() => setDrill(null)}
          loading={!drillData && !drillError}
          error={drillError}
        />
      )}
    </>
  );
}

// =============================================================================
// Full-screen modal — 100vw × 100vh canvas, slim 40px top bar, optional
// collapsible left filter rail (240px) with legend + per-type checkboxes.
// =============================================================================

// Fact list surfaced to the side legend when a class node (or one of its
// fact children) is clicked in the evidence map.
interface SelectedClassFacts {
  className: string;
  facts: {
    id: string;
    title: string;
    source: string;
    source_kind: string;
  }[];
}

type GraphModalProps = {
  title: string;
  subtitle?: string;
  defaultLayout: LayoutName;
  onClose: () => void;
  // Either pre-computed `elements` (evidence map) or raw nodes/edges that
  // need to be re-mapped when filters change (knowledge graph).
  elements?: CyElement[];
  rawNodes?: ApiNode[];
  rawEdges?: ApiEdge[];
  hideFilters?: boolean;
  hidden?: Set<GraphFilterType>;
  // Render the modal chrome immediately on Expand click, even before the
  // upstream fetch resolves. `loading` blanks the canvas with a spinner
  // message; `error` surfaces the fetch failure inside the modal so the
  // user isn't left staring at an empty screen.
  loading?: boolean;
  error?: string | null;
  // Evidence variant only — passed by EvidenceMap / PlatformFlowModal so
  // a double-click on a Neo4j-backed node can pop the Knowledge-graph
  // modal stacked on top of this one. `active` is the case the drill
  // handler reads to compute the anchor.
  onDrill?: (target: DrillTarget) => void;
  active?: CaseFull | null;
};

function GraphModal({
  title,
  subtitle,
  defaultLayout,
  onClose,
  elements: precomputed,
  rawNodes,
  rawEdges,
  hideFilters,
  hidden: hiddenProp,
  loading,
  error,
  onDrill,
  active,
}: GraphModalProps) {
  const [layout, setLayout] = useState<LayoutName>(defaultLayout);
  const [layoutMenuOpen, setLayoutMenuOpen] = useState(false);
  const [legendOpen, setLegendOpen] = useState(true);
  const [selectedClassFacts, setSelectedClassFacts] = useState<SelectedClassFacts | null>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const hiddenSub = useFilterSubscription();
  const hidden = hiddenProp ?? hiddenSub;

  const elements = useMemo(() => {
    if (precomputed) return precomputed;
    if (rawNodes && rawEdges) return toCyElements(rawNodes, rawEdges, hidden);
    return [];
  }, [precomputed, rawNodes, rawEdges, hidden]);

  // Close on Escape.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Re-fit when the canvas resizes (legend toggle changes width).
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const t = setTimeout(() => cy.fit(undefined, 40), 240);
    return () => clearTimeout(t);
  }, [legendOpen]);

  // Run a fresh layout when the underlying element set changes (filters
  // toggled) OR when the user picks a new layout from the dropdown.
  // Auto-fit on layoutstop AND via a backup timeout, so the canvas is
  // never left blank even if the layout never fires its stop event.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || elements.length === 0) return;
    let cancelled = false;
    const safeFit = () => {
      if (cancelled) return;
      try { cy.fit(undefined, 40); } catch { /* swallow */ }
    };
    const runOne = (name: LayoutName) => {
      const l = cy.layout(layoutOptions(name));
      l.on("layoutstop", safeFit);
      l.run();
    };
    try {
      runOne(layout);
    } catch (e) {
      console.warn("Layout", layout, "failed, falling back to cose:", e);
      try { runOne("cose"); } catch { /* swallow */ }
    }
    // Belt-and-braces: even if layoutstop fires too early or never, this
    // timer guarantees a fit after the browser has painted.
    const t = setTimeout(safeFit, 300);
    return () => { cancelled = true; clearTimeout(t); };
  }, [elements.length, layout]);

  // Derive per-type counts for the topbar and legend. (Relationships are
  // labelled directly on the edges now, not enumerated in the side panel.)
  const typeCounts = useMemo(() => deriveTypeCounts(precomputed, rawNodes), [precomputed, rawNodes]);

  const resetView = () => {
    cyRef.current?.zoom(1);
    cyRef.current?.center();
  };
  const topView = () => cyRef.current?.fit(undefined, 40);
  const refresh = () => {
    const cy = cyRef.current;
    if (!cy) return;
    const l = cy.layout(layoutOptions(layout));
    l.on("layoutstop", () => cy.fit(undefined, 40));
    l.run();
  };
  const reLayout = (next: LayoutName) => {
    // setLayout triggers the useEffect that actually runs the layout
    // (with fit-on-layoutstop + fallback). Running layout here too
    // double-fires and can leave compound graphs blank.
    setLayout(next);
    setLayoutMenuOpen(false);
  };

  // Render into a portal so position:fixed escapes any ancestor that
  // creates a positioning/stacking context. Without this the modal can be
  // clamped to an ancestor's box and visually appear smaller than the viewport.
  const variant = hideFilters ? "evidence" : "knowledge";
  const modal = (
    <div className="graph-modal-backdrop" onClick={onClose}>
      <div className={`graph-modal variant-${variant}`} onClick={(e) => e.stopPropagation()}>
        <header className="graph-modal-stats-bar">
          <div className="graph-modal-stats-left">
            <span className="graph-modal-stats-title">{title}</span>
            {typeCounts.length > 0 && (
              <span className="graph-modal-stats-counts">
                {typeCounts.map((tc, i) => (
                  <span key={tc.type} className="graph-modal-stat-item">
                    {i > 0 && <span className="graph-modal-stat-sep">·</span>}
                    <strong>{tc.count}</strong> {pluralType(tc.type, tc.count)}
                  </span>
                ))}
              </span>
            )}
          </div>
          <div className="graph-modal-stats-right">
            <div className="graph-modal-layout-menu">
              <button
                type="button"
                className="graph-toolbar-btn"
                onClick={() => setLayoutMenuOpen((x) => !x)}
              >
                Layout · {layout} ▾
              </button>
              {layoutMenuOpen && (
                <div className="graph-modal-layout-dropdown" onMouseLeave={() => setLayoutMenuOpen(false)}>
                  {(["cose", "dagre", "breadthfirst", "circle", "grid"] as LayoutName[]).map((l) => (
                    <button
                      key={l}
                      type="button"
                      className={`graph-modal-layout-option${layout === l ? " active" : ""}`}
                      onClick={() => reLayout(l)}
                    >
                      {l}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button className="graph-toolbar-btn" type="button" onClick={refresh}>↻ Refresh</button>
            <button className="graph-toolbar-btn" type="button" onClick={resetView}>Reset</button>
            <button className="graph-toolbar-btn" type="button" onClick={topView}>↑ Top</button>
            <button
              className="graph-modal-close"
              type="button"
              onClick={onClose}
              aria-label="Close"
            >×</button>
          </div>
        </header>
        <div className="graph-modal-stage">
          <div className="graph-modal-canvas">
            {loading && (
              <div className="graph-modal-state">
                <div className="graph-modal-state-eyebrow">Loading subgraph…</div>
                <div className="graph-modal-state-body">
                  Walking Neo4j {`up to 4 hops out from the case subject. This usually takes < 2 seconds.`}
                </div>
              </div>
            )}
            {error && (
              <div className="graph-modal-state error">
                <div className="graph-modal-state-eyebrow">Could not load subgraph</div>
                <div className="graph-modal-state-body">{error}</div>
              </div>
            )}
            {!loading && !error && (
              <CytoscapeComponent
                elements={elements}
                // `layout` is pinned to `preset` so react-cytoscapejs never
                // re-runs a layout on prop change. We manage every layout
                // run ourselves (see runLayout). Without this pin, the
                // library races our own layout call when the user picks a
                // new option from the dropdown, corrupting node positions
                // and leaving the canvas blank.
                layout={PRESET_LAYOUT}
                stylesheet={variant === "evidence" ? evidenceStylesheet : knowledgeStylesheet}
                style={{ width: "100%", height: "100%" }}
                wheelSensitivity={0.2}
                cy={(cy) => {
                  cyRef.current = cy;
                  // Cap zoom so cy.fit() never enlarges nodes past their
                  // intrinsic size — without this, small dots cause the
                  // Editorial knowledge graph to zoom 4–5× in and the
                  // serif labels stack on top of each other.
                  cy.maxZoom(1.4);
                  cy.minZoom(0.2);
                  attachInteractivity(cy);
                  attachEvidenceMapBehaviour(cy, setSelectedClassFacts, onDrill ?? null, active ?? null);
                }}
              />
            )}
          </div>
          <GraphModalSideLegend
            open={legendOpen}
            onToggle={() => setLegendOpen((x) => !x)}
            variant={variant}
            typeCounts={typeCounts}
            subtitle={subtitle}
            selectedClassFacts={selectedClassFacts}
            onDismissFacts={() => setSelectedClassFacts(null)}
            drillHint={
              variant === "evidence" && active && DRILL_HANDLERS.neo4j.available(active)
                ? DRILL_HANDLERS.neo4j.hint
                : null
            }
          />
        </div>
      </div>
    </div>
  );
  return createPortal(modal, document.body);
}

// -----------------------------------------------------------------------------
// Right-side legend panel — always visible (can collapse). Lists every node
// type with its swatch (and a count when known), every relationship type
// rendered as a small arrow icon, and a click-to-inspect caption.
// -----------------------------------------------------------------------------
function GraphModalSideLegend({
  open,
  onToggle,
  variant,
  typeCounts,
  subtitle,
  selectedClassFacts,
  onDismissFacts,
  drillHint,
}: {
  open: boolean;
  onToggle: () => void;
  variant: "knowledge" | "evidence";
  typeCounts: { type: string; count: number }[];
  subtitle?: string;
  selectedClassFacts?: SelectedClassFacts | null;
  onDismissFacts?: () => void;
  drillHint?: string | null;
}) {
  return (
    <aside className={`graph-modal-side-legend${open ? "" : " collapsed"}`}>
      <button type="button" className="graph-modal-side-legend-toggle" onClick={onToggle}>
        <span>LEGEND</span>
        <span aria-hidden="true">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="graph-modal-side-legend-body">
          {subtitle && <div className="graph-modal-side-legend-subtitle">{subtitle}</div>}
          {selectedClassFacts && selectedClassFacts.facts.length > 0 && (
            <div className="graph-modal-side-legend-section selection-section">
              <div className="graph-modal-side-legend-section-label selection-label">
                <span>Facts · {selectedClassFacts.className} ({selectedClassFacts.facts.length})</span>
                {onDismissFacts && (
                  <button
                    type="button"
                    className="graph-modal-side-legend-dismiss"
                    onClick={onDismissFacts}
                    aria-label="Clear selection"
                  >×</button>
                )}
              </div>
              <div className="graph-modal-side-legend-facts">
                {selectedClassFacts.facts.map((f, i) => (
                  <details key={`${f.id}-${i}`} className="graph-modal-fact-row">
                    <summary className="graph-modal-fact-summary">
                      <span className="graph-modal-fact-id">{f.id}</span>
                      <span className="graph-modal-fact-title">{f.title}</span>
                    </summary>
                    <div className="graph-modal-fact-detail">
                      <span className="graph-modal-fact-meta">source:</span> {f.source}
                    </div>
                  </details>
                ))}
              </div>
            </div>
          )}
          <div className="graph-modal-side-legend-section">
            <div className="graph-modal-side-legend-section-label">Node types</div>
            <div className="graph-modal-side-legend-rows">
              {typeCounts.length > 0
                ? typeCounts.map((tc) => (
                    <div key={tc.type} className="graph-modal-side-legend-row">
                      <span className={`graph-legend-dot ${dotClassFor(variant, tc.type)}`} aria-hidden="true" />
                      <span className="graph-modal-side-legend-name">{tc.type}</span>
                    </div>
                  ))
                : (variant === "knowledge"
                    ? KNOWLEDGE_LEGEND
                    : EVIDENCE_LEGEND
                  ).map((it) => (
                    <div key={it.label} className="graph-modal-side-legend-row">
                      <span className={`graph-legend-dot ${it.cls}`} aria-hidden="true" />
                      <span className="graph-modal-side-legend-name">{it.label}</span>
                    </div>
                  ))}
            </div>
          </div>
          {variant === "evidence" && (
            <div className="graph-modal-side-legend-section">
              <div className="graph-modal-side-legend-section-label">Relationships</div>
              <div className="graph-modal-side-legend-rows">
                {EVIDENCE_RELATIONSHIPS.map((r) => (
                  <div key={r.label} className="graph-modal-side-legend-row">
                    <span className="graph-legend-edge-swatch" style={{ background: r.color }} aria-hidden="true" />
                    <span className="graph-modal-side-legend-name">{r.label}</span>
                    <span className="graph-modal-side-legend-meta">{r.description}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="graph-modal-side-legend-caption">
            Click any node to inspect.{" "}
            {drillHint && (<><br/>{drillHint}<br/></>)}
            Scroll to zoom, drag to pan.
          </div>
        </div>
      )}
    </aside>
  );
}

const KNOWLEDGE_LEGEND = [
  { cls: "viz-dot-anchor",    label: "anchor (case subject)" },
  { cls: "viz-dot-risk",      label: "sanctioned" },
  { cls: "viz-dot-risk_path", label: "on sanctions path" },
  { cls: "viz-dot-alt",       label: "carrier / alliance" },
  { cls: "viz-dot-default",   label: "1-hop neighbour" },
];
const EVIDENCE_LEGEND = [
  { cls: "viz-dot-prompt",  label: "prompt" },
  { cls: "viz-dot-stage",   label: "stage" },
  { cls: "viz-dot-class",   label: "ontology class" },
  { cls: "viz-dot-source",  label: "data source" },
  { cls: "viz-dot-outcome", label: "outcome" },
];

// Edge-relationship swatches for the evidence map. Each maps to one of
// the `edge.edge-rel-*` selectors in evidenceStylesheet; the colour here
// must stay in sync with the Cytoscape rule.
const EVIDENCE_RELATIONSHIPS = [
  { label: "intake",   color: "#1e293b", description: "prompt → stage" },
  { label: "queries",  color: "#0d6e7f", description: "stage → class" },
  { label: "resolves", color: "#7c3aed", description: "class → source" },
  { label: "informs",  color: "#d97706", description: "source → outcome" },
];

function dotClassFor(variant: "knowledge" | "evidence", ontologyType: string): string {
  if (variant === "evidence") {
    if (ontologyType.includes("prompt")) return "viz-dot-prompt";
    if (ontologyType.includes("stage")) return "viz-dot-stage";
    if (ontologyType.includes("source")) return "viz-dot-source";
    if (ontologyType.includes("outcome")) return "viz-dot-outcome";
    return "viz-dot-class";
  }
  // Knowledge variant — map ontology type to swatch class.
  return `dot-type-${ontologyType}`;
}

function deriveTypeCounts(
  precomputed: CyElement[] | undefined,
  rawNodes: ApiNode[] | undefined,
): { type: string; count: number }[] {
  const counts = new Map<string, number>();
  if (rawNodes) {
    for (const n of rawNodes) counts.set(n.type, (counts.get(n.type) || 0) + 1);
  } else if (precomputed) {
    for (const e of precomputed) {
      if (!e.classes || !String(e.classes).includes("evidence-node")) continue;
      // Evidence-map labels aren't ontology types — skip the per-type
      // header for the evidence variant.
    }
  }
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([type, count]) => ({ type, count }));
}

function pluralType(t: string, n: number): string {
  if (n === 1) return t;
  if (t.endsWith("y")) return t.slice(0, -1) + "ies";
  if (t.endsWith("s")) return t;
  return t + "s";
}

// =============================================================================
// Interactivity — click a node to highlight it + adjacent edges + neighbours
// =============================================================================

// Evidence-map-specific behaviour:
//   - Single-click on a class node surfaces its fact list to the side
//     legend dropdown (facts are embedded on data.facts).
//   - Double-click on any `evidence-drillable` node (class OR source
//     tile from Neo4j) fires onDrill with the computed DrillTarget,
//     stacking the Knowledge-graph modal on top of the evidence modal.
//
// Idempotent + scratch-backed: react-cytoscapejs re-invokes the `cy={fn}`
// callback every time the parent renders, and a sibling helper
// (attachInteractivity) calls `cy.off("tap")` which would wipe a
// closure-based lastTap on every re-attach. We store the live callbacks
// AND lastTap on cy.scratch so React state updates (e.g. surfacing
// facts) don't break the second click of a double-click.
function attachEvidenceMapBehaviour(
  cy: cytoscape.Core,
  setSelectedClassFacts: (facts: SelectedClassFacts | null) => void,
  onDrill: ((target: DrillTarget) => void) | null,
  active: CaseFull | null,
) {
  // Always update the latest callbacks — the persisted handler reads
  // them via scratch on every tap.
  cy.scratch("_kfEvi", {
    ...(cy.scratch("_kfEvi") || {}),
    setSelectedClassFacts,
    onDrill,
    active,
  });

  if (cy.scratch("_kfEviAttached")) return;
  cy.scratch("_kfEviAttached", true);

  cy.on("tap", "node", (evt: any) => {
    const node = evt.target;
    const id = node.id();
    const now = Date.now();
    const state: any = cy.scratch("_kfEvi") || {};
    const lastTap = state.lastTap as { id: string; time: number } | null;
    const isDouble = !!lastTap && lastTap.id === id && now - lastTap.time < 350;
    cy.scratch("_kfEvi", { ...state, lastTap: isDouble ? null : { id, time: now } });

    const cb = cy.scratch("_kfEvi") as any;
    if (isDouble && cb?.onDrill && cb?.active && node.hasClass("evidence-drillable")) {
      const kind = String(node.data("drill_kind") || "");
      const handler = DRILL_HANDLERS[kind];
      const target = handler?.target(cb.active);
      if (target) cb.onDrill(target);
      return;
    }

    const setFacts = cb?.setSelectedClassFacts as ((f: SelectedClassFacts | null) => void) | undefined;
    if (!setFacts) return;
    if (!node.classes().includes("evidence-class")) {
      setFacts(null);
      return;
    }
    const className = String(node.data("label") || id).split("\n")[0];
    const facts = (node.data("facts") || []) as Array<{
      id: string;
      title: string;
      source: string;
      source_kind: string;
    }>;
    setFacts({ className, facts });
  });

  cy.on("tap", (evt: any) => {
    if (evt.target === cy) {
      const cb = cy.scratch("_kfEvi") as any;
      cb?.setSelectedClassFacts?.(null);
    }
  });
}

function attachInteractivity(cy: cytoscape.Core) {
  // Idempotent — react-cytoscapejs re-invokes the cy callback on every
  // parent re-render. Without this guard we'd cy.off("tap") on every
  // re-render, wiping the evidence-map double-click closure state
  // along with the focus handler.
  if (cy.scratch("_kfInterAttached")) return;
  cy.scratch("_kfInterAttached", true);

  cy.on("tap", "node", (evt: any) => {
    const node = evt.target;
    // If this node was already highlighted, clear and bail.
    if (node.hasClass("cy-focus")) {
      cy.elements().removeClass("cy-focus cy-dim");
      return;
    }
    cy.elements().removeClass("cy-focus cy-dim");
    cy.elements().addClass("cy-dim");
    const neighbourhood = node.closedNeighborhood();
    neighbourhood.removeClass("cy-dim").addClass("cy-focus");
  });

  cy.on("tap", (evt: any) => {
    if (evt.target === cy) {
      cy.elements().removeClass("cy-focus cy-dim");
    }
  });
}

// React hook — subscribe to the global hidden-types store and re-render.
function useFilterSubscription(): Set<GraphFilterType> {
  const [hidden, setHidden] = useState<Set<GraphFilterType>>(() => getHiddenGraphTypes());
  useEffect(() => subscribeHiddenGraphTypes(setHidden), []);
  return hidden;
}

// =============================================================================
// Layout config per name
// =============================================================================

function layoutOptions(name: LayoutName): any {
  switch (name) {
    case "dagre":
      return { name: "dagre", rankDir: "LR", nodeSep: 30, rankSep: 80, edgeSep: 12 };
    case "breadthfirst":
      return { name: "breadthfirst", directed: true, padding: 30, spacingFactor: 1.2 };
    case "circle":
      return { name: "circle", padding: 30 };
    case "grid":
      return { name: "grid", padding: 30 };
    case "cose":
    default:
      return {
        name: "cose",
        nodeRepulsion: 9000,
        idealEdgeLength: 110,
        edgeElasticity: 0.45,
        padding: 30,
        animate: false,
      };
  }
}

// =============================================================================
// Helpers — anchor detection, element transformers
// =============================================================================

function toCyElements(
  nodes: ApiNode[],
  edges: ApiEdge[],
  hidden: Set<GraphFilterType>,
): CyElement[] {
  const out: CyElement[] = [];
  const dropped = new Set<string>();
  for (const n of nodes) {
    if (nodeHiddenBy(hidden, n.type, n.accent)) {
      dropped.add(n.id);
      continue;
    }
    out.push({
      data: {
        id: n.id,
        label: shortenLabel(n.label, 24),
        nodeType: n.type,
        accent: n.accent || "default",
      },
      classes: ["graph-node", `accent-${n.accent || "default"}`, `type-${n.type}`].join(" "),
    });
  }
  for (const e of edges) {
    if (dropped.has(e.source) || dropped.has(e.target)) continue;
    out.push({
      data: {
        id: `${e.source}->${e.target}:${e.type}`,
        source: e.source,
        target: e.target,
        label: e.type,
      },
      classes: ["graph-edge", e.accent ? `edge-accent-${e.accent}` : ""].join(" "),
    });
  }
  return out;
}


function shortenLabel(s: string, max: number): string {
  if (!s || s.length <= max) return s;
  return s.slice(0, max - 1) + "…";
}

function countSourceKinds(active: CaseFull): number {
  const kinds = new Set<string>();
  for (const stage of active.stages || []) {
    for (const f of stage.facts) {
      const src = f.source || "";
      const k = src.includes(":") ? src.split(":", 1)[0] : src;
      if (k) kinds.add(k);
    }
  }
  return kinds.size;
}

function buildEvidenceElements(active: CaseFull): CyElement[] {
  const elements: CyElement[] = [];
  const stages = active.stages || [];

  // 1. Prompt node
  const promptText = (active.prompt || "(prompt)").slice(0, 60);
  elements.push({
    data: { id: "prompt", label: `“${promptText}${active.prompt && active.prompt.length > 60 ? "…" : ""}”` },
    classes: "evidence-node evidence-prompt",
  });

  // 2. Stage nodes + prompt → stage edges. While walking, collect for
  // each ontology class the set of stages it appears in, the set of
  // source kinds it was bound through, and the actual facts.
  const stagesByClass = new Map<string, Set<string>>();
  const sourcesByClass = new Map<string, Set<string>>();
  const factsByClass = new Map<string, FactFlat[]>();
  for (const stage of stages) {
    const stageId = `stage:${stage.stage}`;
    elements.push({
      data: { id: stageId, label: stageLabelFor(stage.stage) },
      classes: "evidence-node evidence-stage",
    });
    elements.push({
      data: {
        id: `edge:prompt:${stageId}`,
        source: "prompt",
        target: stageId,
        label: "intake",
      },
      classes: "evidence-edge edge-rel-intake",
    });
    for (const f of stage.facts) {
      const cls = f.ontology_type;
      const src = f.source || "?";
      const kind = src.includes(":") ? src.split(":", 1)[0] : src;
      if (!stagesByClass.has(cls)) stagesByClass.set(cls, new Set());
      stagesByClass.get(cls)!.add(stageId);
      if (!sourcesByClass.has(cls)) sourcesByClass.set(cls, new Set());
      sourcesByClass.get(cls)!.add(kind);
      if (!factsByClass.has(cls)) factsByClass.set(cls, []);
      factsByClass.get(cls)!.push({
        id: f.id,
        title: f.title || f.id,
        source: src,
        source_kind: kind,
        ontology_type: cls,
      });
    }
  }

  // 3. One class node per distinct ontology_type — simple node, not a
  // compound parent. The full fact list is embedded in `data.facts` so
  // the side legend can render it when the class is clicked. Classes
  // whose facts came from a drill-capable source (today: Neo4j) get an
  // `evidence-drillable` class + a corner glyph + drill metadata.
  for (const [cls, stageSet] of stagesByClass.entries()) {
    const classId = `class:${cls}`;
    const facts = factsByClass.get(cls) || [];
    const srcs = sourcesByClass.get(cls) || new Set();
    const drillKind = drillKindFor(srcs, active);
    elements.push({
      data: {
        id: classId,
        label: `${cls}\n(${facts.length} fact${facts.length === 1 ? "" : "s"})`,
        facts,
        ...(drillKind ? {
          drill_kind: drillKind,
          drill_glyph_uri: drillGlyphSvgUri(),
        } : {}),
      },
      classes: drillKind
        ? "evidence-node evidence-class evidence-drillable"
        : "evidence-node evidence-class",
    });
    for (const stageId of stageSet) {
      elements.push({
        data: {
          id: `edge:${stageId}:${classId}`,
          source: stageId,
          target: classId,
          label: "queries",
        },
        classes: "evidence-edge edge-rel-queries",
      });
    }
  }

  // 4. Source nodes (one per distinct kind) + class → source edges.
  // A source whose kind has a registered drill handler (today: neo4j)
  // gets the same drillable tagging as its consuming classes.
  const allSourceKinds = new Set<string>();
  for (const set of sourcesByClass.values()) for (const k of set) allSourceKinds.add(k);
  for (const kind of allSourceKinds) {
    const drillKind = drillKindFor([kind], active);
    elements.push({
      data: {
        id: `source:${kind}`,
        label: humanSourceKind(kind),
        ...(drillKind ? {
          drill_kind: drillKind,
          drill_glyph_uri: drillGlyphSvgUri(),
        } : {}),
      },
      classes: drillKind
        ? "evidence-node evidence-source evidence-drillable"
        : "evidence-node evidence-source",
    });
  }
  for (const [cls, srcSet] of sourcesByClass.entries()) {
    const classId = `class:${cls}`;
    for (const kind of srcSet) {
      elements.push({
        data: {
          id: `edge:${classId}:source:${kind}`,
          source: classId,
          target: `source:${kind}`,
          label: "resolves",
        },
        classes: "evidence-edge edge-rel-resolves",
      });
    }
  }

  // 5. Outcome node — always rendered so the flow visually ends at a
  // decision box. While the case is in progress the outcome shows
  // "Pending decision"; once complete it flips to the chosen decision.
  const outcomeLabel = active.phase === "complete" && active.decision_kind
    ? `Outcome · ${active.decision_kind.replace(/_/g, " ")}`
    : "Outcome · pending";
  elements.push({
    data: { id: "outcome", label: outcomeLabel },
    classes: active.phase === "complete"
      ? "evidence-node evidence-outcome"
      : "evidence-node evidence-outcome evidence-pending",
  });
  for (const kind of allSourceKinds) {
    elements.push({
      data: {
        id: `edge:source:${kind}:outcome`,
        source: `source:${kind}`,
        target: "outcome",
        label: "informs",
      },
      classes: "evidence-edge edge-rel-informs",
    });
  }
  return elements;
}

interface FactFlat {
  id: string;
  title: string;
  source: string;
  source_kind: string;
  ontology_type: string;
}

function stageLabelFor(stage: string): string {
  switch (stage) {
    case "agent_intake": return "Policy & scope";
    case "proposal":     return "Agent gathered";
    case "review":       return "For your decision";
    default:             return stage;
  }
}

function humanSourceKind(k: string): string {
  switch (k) {
    case "csv":          return "CSV";
    case "sqlite":       return "SQLite";
    case "postgres":     return "Postgres";
    case "neo4j":        return "Neo4j graph";
    case "http":         return "HTTP API";
    case "vector_store": return "Vector store";
    case "kf":           return "KF graph (inline)";
    case "iam":          return "IAM";
    case "tms":          return "TMS";
    case "erp":          return "ERP";
    case "finance":      return "Finance";
    case "governance":   return "Governance";
    default:             return k.toUpperCase();
  }
}

// =============================================================================
// Platform Flow modal — per-case explorer answering "how did the platform
// answer this query?" by drawing a single left-to-right chain:
//
//   Query → Scenario → Ontology classes → Data sources → Outcome
//
// Edges are labelled ("classified as", "queries", "binds to", "informed") so
// a non-engineer can read the chart. Built from the live case payload — no
// extra API calls.
// =============================================================================

export function PlatformFlowModal({
  active,
  onClose,
}: {
  active: CaseFull | null;
  onClose: () => void;
}) {
  const [drill, setDrill] = useState<DrillTarget | null>(null);
  const elements = useMemo(
    () => (active ? buildPlatformFlowElements(active) : []),
    [active],
  );
  const drillAnchor = drill?.kind === "knowledge-graph" ? drill.anchor : null;
  const { data: drillData, error: drillError } = useSupplierSubgraph(
    drillAnchor?.supplier_id ?? null,
    !!drillAnchor,
  );
  if (!active) {
    return (
      <GraphModal
        title="Platform flow"
        subtitle="Open a case to see how the platform answered the query."
        elements={[]}
        defaultLayout="dagre"
        onClose={onClose}
        hideFilters
      />
    );
  }
  const promptOneLine = (active.prompt || "(no prompt)").replace(/\s+/g, " ");
  return (
    <>
      <GraphModal
        title="Platform flow"
        subtitle={`How the platform answered: "${truncate(promptOneLine, 90)}"`}
        elements={elements}
        defaultLayout="dagre"
        onClose={onClose}
        hideFilters
        onDrill={setDrill}
        active={active}
      />
      {drillAnchor && (
        <GraphModal
          title="Knowledge graph"
          subtitle={`${drillAnchor.supplier_id} · ${drillAnchor.supplierName}`}
          rawNodes={drillData?.nodes}
          rawEdges={drillData?.edges}
          defaultLayout="dagre"
          onClose={() => setDrill(null)}
          loading={!drillData && !drillError}
          error={drillError}
        />
      )}
    </>
  );
}

function buildPlatformFlowElements(active: CaseFull): CyElement[] {
  const out: CyElement[] = [];
  const stages = active.stages || [];
  const allFacts = stages.flatMap((s) => s.facts || []);

  // 1. Query node — the operator's prompt.
  const prompt = active.prompt || "(no prompt)";
  out.push({
    data: { id: "pf:query", label: `Query\n"${truncate(prompt, 50)}"` },
    classes: "evidence-node evidence-prompt",
  });

  // 2. Scenario node — the matched recipe (always present once binding fires).
  if (active.scenario_id) {
    const scenarioLabel = active.scenario?.title
      ? `${active.scenario_id}\n${truncate(active.scenario.title, 50)}`
      : active.scenario_id;
    out.push({
      data: { id: "pf:scenario", label: `Scenario\n${scenarioLabel}` },
      classes: "evidence-node evidence-scenario",
    });
    out.push({
      data: {
        id: "pf:edge:query-scenario",
        source: "pf:query",
        target: "pf:scenario",
        label: "classified as",
      },
      classes: "evidence-edge",
    });
  }

  // 3. Ontology classes — distinct ontology_type values across all stages.
  // A class becomes drillable when any of its facts came from a source
  // kind that has a registered drill handler (today: Neo4j).
  const ontologyTypes = distinct(allFacts.map((f) => f.ontology_type));
  for (const ot of ontologyTypes) {
    const id = `pf:class:${ot}`;
    const classSrcKinds = new Set(
      allFacts.filter((f) => f.ontology_type === ot).map((f) => firstSegment(f.source)),
    );
    const drillKind = drillKindFor(classSrcKinds, active);
    out.push({
      data: {
        id,
        label: ot,
        ...(drillKind ? {
          drill_kind: drillKind,
          drill_glyph_uri: drillGlyphSvgUri(),
        } : {}),
      },
      classes: drillKind
        ? "evidence-node evidence-class evidence-drillable"
        : "evidence-node evidence-class",
    });
    if (active.scenario_id) {
      out.push({
        data: {
          id: `pf:edge:scenario-class:${ot}`,
          source: "pf:scenario",
          target: id,
          label: "queries",
        },
        classes: "evidence-edge",
      });
    }
  }

  // 4. Data sources — distinct source kinds, edges from each ontology class
  // to every source that actually returned that class's facts.
  const sourceKinds = distinct(allFacts.map((f) => firstSegment(f.source)));
  for (const src of sourceKinds) {
    const id = `pf:source:${src}`;
    const drillKind = drillKindFor([src], active);
    out.push({
      data: {
        id,
        label: humanSourceKind(src),
        ...(drillKind ? {
          drill_kind: drillKind,
          drill_glyph_uri: drillGlyphSvgUri(),
        } : {}),
      },
      classes: drillKind
        ? "evidence-node evidence-source evidence-drillable"
        : "evidence-node evidence-source",
    });
    const classesForSource = distinct(
      allFacts.filter((f) => firstSegment(f.source) === src).map((f) => f.ontology_type),
    );
    for (const ot of classesForSource) {
      const factCount = allFacts.filter(
        (f) => firstSegment(f.source) === src && f.ontology_type === ot,
      ).length;
      out.push({
        data: {
          id: `pf:edge:class-source:${ot}:${src}`,
          source: `pf:class:${ot}`,
          target: id,
          label: factCount > 1 ? `returned ${factCount} facts` : "returned 1 fact",
        },
        classes: "evidence-edge",
      });
    }
  }

  // 5. Outcome — always rendered so the flow visually ends at a
  // decision box. "Pending decision" while the case is in progress,
  // flips to the chosen decision once complete.
  const isComplete = active.phase === "complete" && !!active.decision_kind;
  const outcomeLabel = isComplete
    ? `Outcome\n${active.decision_kind!.replace(/_/g, " ")}`
    : "Outcome\npending";
  out.push({
    data: { id: "pf:outcome", label: outcomeLabel },
    classes: isComplete
      ? "evidence-node evidence-outcome"
      : "evidence-node evidence-outcome evidence-pending",
  });
  for (const src of sourceKinds) {
    out.push({
      data: {
        id: `pf:edge:source-outcome:${src}`,
        source: `pf:source:${src}`,
        target: "pf:outcome",
        label: "informs",
      },
      classes: "evidence-edge edge-rel-informs",
    });
  }

  return out;
}

function distinct<T>(xs: T[]): T[] {
  const seen = new Set<T>();
  const out: T[] = [];
  for (const x of xs) {
    if (x && !seen.has(x)) { seen.add(x); out.push(x); }
  }
  return out;
}

function firstSegment(src: string | null | undefined): string {
  if (!src) return "?";
  return src.includes(":") ? src.split(":", 1)[0] : src;
}

function truncate(s: string, max: number): string {
  if (!s || s.length <= max) return s;
  return s.slice(0, max - 1) + "…";
}

// =============================================================================
// Cytoscape stylesheet — cleaner enterprise palette + a single base shape
// (rounded rectangles) so the eye reads the network as one kind of thing.
// Sanctioned entities keep the same shape but get a saturated border so they
// pop. Carrier/Alliance keep the rounded rectangle but use a warm sand fill.
// =============================================================================

// Shared interaction states — applied at runtime by the click/search
// handlers. Layered on top of either variant stylesheet.
const SHARED_INTERACTION: any[] = [
  // Click-to-focus: dashed indigo outline on the focused subgraph, the
  // rest dimmed hard.
  {
    selector: "node.cy-focus",
    style: {
      "border-width": 2,
      "border-color": "#4f46e5",
      "border-style": "dashed",
      "z-index": 99,
      "opacity": 1,
    },
  },
  {
    selector: "edge.cy-focus",
    style: {
      "line-color": "#4f46e5",
      "target-arrow-color": "#4f46e5",
      width: 2,
      "opacity": 1,
      "z-index": 99,
    },
  },
  { selector: ".cy-dim", style: { "opacity": 0.18 } },
  {
    selector: ".cy-search-hit",
    style: {
      "border-width": 2,
      "border-color": "#4f46e5",
      "border-style": "dashed",
      "z-index": 100,
    },
  },
  { selector: ".cy-search-miss", style: { "opacity": 0.22 } },
];

// =============================================================================
// Knowledge-graph stylesheet — Style 3 "Editorial"
// =============================================================================
// Each node is a small coloured dot (no glyph inside) with an italic serif
// name placed below in Fraunces. Edges are 0.6-px hairlines with a small
// terminal dot instead of an arrowhead. Designed for the cream "publication"
// canvas (CSS sets the background on .graph-modal.variant-knowledge).
const knowledgeStylesheet: any[] = [
  {
    selector: "node.graph-node",
    style: {
      shape: "ellipse",
      "background-color": "#5a6678",
      "border-color": "rgba(15,23,42,0.15)",
      "border-width": 1,
      width: 18,
      height: 18,
      label: "data(label)",
      color: "#0f172a",
      "font-family": "Fraunces, Georgia, serif",
      "font-style": "italic",
      "font-size": 9,
      "font-weight": 400,
      "text-valign": "bottom",
      "text-halign": "center",
      "text-margin-y": 4,
      "text-wrap": "wrap",
      "text-max-width": 110,
      "min-zoomed-font-size": 5,
    },
  },
  // Anchor — deep teal, slightly larger.
  {
    selector: "node.accent-anchor",
    style: {
      "background-color": "#0d6e7f",
      "border-color": "#0a4f5c",
      "border-width": 1.5,
      width: 26,
      height: 26,
      "font-weight": 600,
      "font-size": 10,
      color: "#0a4f5c",
    },
  },
  // Sanctioned — muted red.
  {
    selector: "node.accent-risk",
    style: {
      "background-color": "#c14a4a",
      "border-color": "#7a2424",
      "border-width": 1.5,
      width: 22,
      height: 22,
      color: "#7a2424",
    },
  },
  // On a sanctions path — neutral slate with a red ring.
  {
    selector: "node.accent-risk_path",
    style: {
      "background-color": "#94a3b8",
      "border-color": "#c14a4a",
      "border-width": 1.5,
      color: "#7a2424",
    },
  },
  // Carrier / Alliance — warm amber-brown.
  {
    selector: "node.accent-alt",
    style: {
      "background-color": "#a16207",
      "border-color": "#854d0e",
      color: "#854d0e",
    },
  },
  // 1-hop neighbour — soft grey, recedes.
  {
    selector: "node.accent-default",
    style: {
      "background-color": "#cbd5e1",
      "border-color": "rgba(15,23,42,0.15)",
      color: "#475569",
    },
  },

  // Edges — hairlines (no arrowhead), dark ink for paper feel.
  {
    selector: "edge.graph-edge",
    style: {
      width: 0.6,
      "line-color": "rgba(15,23,42,0.55)",
      "target-arrow-shape": "none",
      "curve-style": "bezier",
      // Relationship-type label kept (very small, no background pill).
      label: "data(label)",
      "font-family": "DM Mono, ui-monospace, monospace",
      "font-size": 9,
      "text-rotation": "autorotate",
      color: "rgba(15,23,42,0.55)",
      "text-background-opacity": 0,
    },
  },
  {
    selector: "edge.edge-accent-risk_path",
    style: {
      "line-color": "#c14a4a",
      width: 1,
    },
  },

  ...SHARED_INTERACTION,
];

// =============================================================================
// Evidence-map stylesheet — Style 1 "Soft Glass"
// =============================================================================
// Each node is a white rounded card with a tiny coloured accent ribbon on
// the left edge (encoded by the evidence-* class). Off-white canvas + thin
// border + faint inner shadow simulated via thin double border.
const evidenceStylesheet: any[] = [
  {
    selector: "node.evidence-node",
    style: {
      "background-color": "#ffffff",
      "border-color": "#e5e7eb",
      "border-width": 1,
      color: "#0f172a",
      label: "data(label)",
      "font-family": "-apple-system, BlinkMacSystemFont, Inter, system-ui, sans-serif",
      "font-size": 12,
      "font-weight": 600,
      "text-valign": "center",
      "text-halign": "center",
      "text-wrap": "wrap",
      "text-max-width": 180,
      shape: "round-rectangle",
      padding: 14,
      width: "label",
      height: "label",
    },
  },
  // Soft accent on the left border encodes type. We use border-color
  // (Cytoscape doesn't have per-side border colour) so the entire border
  // takes the accent — same visual outcome on a white background.
  // Drillable nodes — overlay the indigo "⤢" corner glyph (SVG data URI
  // stamped onto data.drill_glyph_uri in buildEvidenceElements). Anchored
  // to the top-right corner via background-offset-x/y. Single-click still
  // surfaces facts in the side legend; double-click triggers the drill
  // (see attachEvidenceMapBehaviour).
  {
    selector: "node.evidence-drillable",
    style: {
      "background-image": "data(drill_glyph_uri)",
      "background-fit": "none",
      "background-clip": "none",
      "background-image-containment": "over",
      "background-image-opacity": 1,
      "background-width": 16,
      "background-height": 16,
      "background-position-x": "100%",
      "background-position-y": "0%",
      "background-offset-x": -2,
      "background-offset-y": 2,
    },
  },
  { selector: "node.evidence-prompt",   style: { "border-color": "#1e293b", color: "#0f172a" } },
  { selector: "node.evidence-scenario", style: { "border-color": "#c14a4a", color: "#7a2424" } },
  { selector: "node.evidence-stage",    style: { "border-color": "#0d6e7f", color: "#0d6e7f" } },
  { selector: "node.evidence-class",    style: { "border-color": "#7c3aed", color: "#5b21b6" } },
  { selector: "node.evidence-source",   style: { "border-color": "#10b981", color: "#047857" } },
  { selector: "node.evidence-outcome",  style: { "border-color": "#d97706", color: "#92400e" } },
  {
    selector: "node.evidence-outcome.evidence-pending",
    style: {
      "border-color": "#cbd5e1",
      color: "#64748b",
      "border-style": "dashed",
    },
  },
  {
    selector: "edge.evidence-edge",
    style: {
      width: 1.4,
      "line-color": "#cbd5e1",
      "target-arrow-color": "#94a3b8",
      "target-arrow-shape": "triangle",
      "arrow-scale": 1,
      "curve-style": "bezier",
      label: "data(label)",
      "font-family": "DM Mono, ui-monospace, monospace",
      "font-size": 9,
      "text-rotation": "autorotate",
      color: "#64748b",
      "text-background-color": "#fafafa",
      "text-background-opacity": 0.95,
      "text-background-padding": 3,
      "text-background-shape": "round-rectangle",
      "text-border-color": "#e5e7eb",
      "text-border-width": 0.5,
      "text-border-opacity": 1,
    },
  },
  // Per-relationship colour-coding — each evidence-map edge type has its
  // own hue so the chart's "what step is this?" is readable at a glance.
  // The same colours are mirrored in the side-legend Relationships
  // section so reviewers can decode the chart without hovering.
  {
    selector: "edge.edge-rel-intake",
    style: {
      "line-color": "#1e293b",
      "target-arrow-color": "#1e293b",
      color: "#1e293b",
    },
  },
  {
    selector: "edge.edge-rel-queries",
    style: {
      "line-color": "#0d6e7f",
      "target-arrow-color": "#0d6e7f",
      color: "#0d6e7f",
    },
  },
  {
    selector: "edge.edge-rel-resolves",
    style: {
      "line-color": "#7c3aed",
      "target-arrow-color": "#7c3aed",
      color: "#7c3aed",
    },
  },
  {
    selector: "edge.edge-rel-informs",
    style: {
      "line-color": "#d97706",
      "target-arrow-color": "#d97706",
      color: "#d97706",
    },
  },

  ...SHARED_INTERACTION,
];
