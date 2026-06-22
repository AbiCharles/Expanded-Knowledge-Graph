import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import cytoscape from "cytoscape";
import dagre from "cytoscape-dagre";
import CytoscapeComponent from "react-cytoscapejs";

import { CaseFull, FactRow } from "../types";
import {
  GraphNode as ApiNode,
  GraphEdge as ApiEdge,
  SubgraphResponse,
  getSupplierSubgraph,
  getOntologyClasses,
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

export function GraphPanel({
  active,
  openPathwaysSignal,
}: {
  active: CaseFull;
  // Counter prop — when its value changes, GraphPanel opens its modal
  // pre-selected to the Decision-pathways tab. Used by the post-revision
  // flow in CounterfactualCard to deep-link the reviewer straight into
  // the re-rendered pathways view.
  openPathwaysSignal?: number;
}) {
  const anchor = useMemo(() => findGraphAnchor(active), [active]);
  const [modalOpen, setModalOpen] = useState(false);
  const [initialViewMode, setInitialViewMode] = useState<"network" | "pathways">("network");
  // Any positive bump of the signal opens the modal on the Pathways
  // tab. The signal counter is monotonic from Envelope, so even if the
  // user closes and re-triggers, the new value will be > 0 and the
  // effect re-fires.
  useEffect(() => {
    if (!openPathwaysSignal) return;
    setInitialViewMode("pathways");
    setModalOpen(true);
  }, [openPathwaysSignal]);

  // W8 — agent-orchestrator deep-link entry. App.tsx dispatches this
  // event when the URL carries ?launch=aeronova&view=graph|pathways
  // after the case has bound. Default tab is Network; override via
  // CustomEvent detail.tab.
  useEffect(() => {
    if (!anchor) return;
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail || {};
      setInitialViewMode(detail.tab === "pathways" ? "pathways" : "network");
      setModalOpen(true);
    };
    window.addEventListener("open-knowledge-graph", handler);
    return () => window.removeEventListener("open-knowledge-graph", handler);
  }, [anchor]);
  const hidden = useFilterSubscription();
  const { data, error } = useSupplierSubgraph(
    anchor?.supplier_id ?? null,
    modalOpen,
  );
  // Hidden-dependency path nodes: the failing supplier (anchor), every
  // AlternativeSupplier candidate id, plus the via_node_id (typically the
  // shared HoldingCompany) on each alternate. Passed into GraphModal which
  // applies the .cy-hidden-dep-path class to those nodes + the connecting
  // edges so the chain visually pops inside the supply-chain subgraph.
  const hiddenDepPath = useMemo(() => {
    const ids = new Set<string>();
    if (anchor?.supplier_id) ids.add(anchor.supplier_id);
    for (const stage of active.stages ?? []) {
      for (const fact of stage.facts ?? []) {
        if (fact.ontology_type !== "AlternativeSupplier") continue;
        if (fact.id) ids.add(fact.id);
        if (fact.via_node_id) ids.add(fact.via_node_id);
      }
    }
    return Array.from(ids);
  }, [active, anchor]);

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
          explainer={
            "The corporate ownership + supplier network around the case " +
            "subject, pulled live from Neo4j. Each node is a real entity " +
            "(supplier, holding company, sanctioned entity, carrier, " +
            "alliance) and each line is a real relationship between them. " +
            "Click any node to see what ontology class it represents."
          }
          rawNodes={data?.nodes}
          rawEdges={data?.edges}
          defaultLayout="dagre"
          onClose={() => {
            setModalOpen(false);
            // Reset so the next manual open lands on Network again.
            setInitialViewMode("network");
          }}
          loading={!data && !error}
          error={error}
          hidden={hidden}
          hiddenDepPath={hiddenDepPath}
          active={active}
          initialViewMode={initialViewMode}
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
          explainer={
            "A picture of how the case was assembled. Reading left to " +
            "right: your prompt triggers each stage of the agent's " +
            "workflow, each stage queries one or more ontology classes, " +
            "those classes resolve to the underlying data sources, and " +
            "the chain ends at the outcome. Click any node to see what " +
            "it represents; double-click a Neo4j-backed node ⤢ to drill " +
            "into the live graph."
          }
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
          explainer={
            "The corporate ownership + supplier network around the case " +
            "subject, pulled live from Neo4j. Click any node to see what " +
            "ontology class it represents."
          }
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

// Fact list surfaced to the side legend when a class node is clicked.
// Also carries the ontology id so the legend can lazy-fetch the class
// definition (description / attributes / relations) and show it ABOVE
// the facts.
interface SelectedClassFacts {
  className: string;
  ontologyId: string | null;
  facts: {
    id: string;
    title: string;
    source: string;
    source_kind: string;
  }[];
}

// Click-to-reveal record: when an entity node in the knowledge graph
// matches a fact in the case (by id), we stash that fact + the stage it
// came from so the side legend can render a "what this node says in the
// stages" panel. Lets the user look at a graph node and read its evidence
// card without closing the modal and scrolling through stages.
interface EntityFactReveal {
  fact: FactRow;
  stageName: string;
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
  // 2-3 sentence plain-English "what is this graph?" paragraph shown
  // at the top of the side legend. Per-modal copy (evidence map vs
  // knowledge graph vs platform flow).
  explainer?: string;
  // List of node IDs that form a hidden-dependency chain. After each layout
  // pass, these nodes (and any edge whose both endpoints are in the list)
  // get the .cy-hidden-dep-path class so the chain renders amber against
  // the rest of the network. Set by GraphPanel from the case's facts.
  hiddenDepPath?: string[];
  // Which tab to open on. Defaults to "network". Used by the post-revision
  // flow in CounterfactualCard to deep-link straight into Decision pathways.
  initialViewMode?: "network" | "pathways";
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
  explainer,
  hiddenDepPath,
  initialViewMode = "network",
}: GraphModalProps) {
  const [layout, setLayout] = useState<LayoutName>(defaultLayout);
  const [layoutMenuOpen, setLayoutMenuOpen] = useState(false);
  const [legendOpen, setLegendOpen] = useState(true);
  const [selectedClassFacts, setSelectedClassFacts] = useState<SelectedClassFacts | null>(null);
  // Click-to-reveal: when an entity node is tapped, if its id matches one of
  // the case's facts (across any stage), surface that fact's card in the side
  // legend so the user can read what the stages say about this node without
  // closing the modal. Null when the modal is dimmer-only / no case attached.
  const [selectedEntityFact, setSelectedEntityFact] = useState<EntityFactReveal | null>(null);
  // View mode — toggled via the tab strip above the canvas. "network" is the
  // clean overview; "pathways" overlays a per-pathway highlight using the
  // case's decision support data (proposed swap chain stays amber, at-risk
  // program chains glow slate, everything else dims).
  const [viewMode, setViewMode] = useState<"network" | "pathways">(initialViewMode);
  const decisionSupport = useMemo(
    () => computeDecisionSupport(active ?? null),
    [active],
  );
  const cyRef = useRef<cytoscape.Core | null>(null);
  // Bumped once react-cytoscapejs hands us the cy instance — included as a
  // dependency on layout / pathway / hidden-dep effects so they re-run when
  // cy first becomes available. Without this, opening the modal with
  // initialViewMode="pathways" (the post-revision deep-link path) leaves
  // the highlight unapplied because the effect already ran while cyRef was
  // still null. Flipping to Network and back used to work as a side-effect
  // because the viewMode change re-fired the effect after cy had attached.
  const [cyReadyTick, setCyReadyTick] = useState(0);
  // Pathway-impact reveal — double-clicking a colored chain or its
  // failing-supplier root pops a card in the side legend showing the
  // downstream programs touched + dollar exposure. Green chains frame
  // it as "programs protected by this pick"; red chains frame it as
  // "programs still exposed"; the slate context chains drill to the
  // specific program at the terminal of that chain.
  const [pathwayDetail, setPathwayDetail] = useState<{
    variant: "proposed" | "avoid" | "impact" | "failing";
    triggerLabel: string;
    programs: DecisionPath[];
  } | null>(null);
  // Defensive cap on how many times the pathway effect can re-run waiting
  // for cytoscape to ingest the failing node. Without a cap, a misconfigured
  // case (failing node not in the supplier subgraph) would spin forever.
  const pathwayRetriesRef = useRef(0);
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
  // Auto-fit on layoutstop AND via TWO backup timers so the canvas is never
  // left blank or zoomed-out-of-view even if layoutstop fires too early or
  // never. The longer timer (650 ms) catches the slow-mount case where the
  // modal opens, elements arrive, dagre runs against a canvas that hasn't
  // been sized yet, the fit settles on the wrong viewport — then this
  // re-fit recomputes against the final canvas dimensions.
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
    // Belt-and-braces: even if layoutstop fires too early or never, these
    // timers guarantee a fit after the browser has painted. Two delays
    // because react-cytoscapejs mount + dagre on 15+ nodes can exceed
    // 300 ms on a cold start.
    const t1 = setTimeout(safeFit, 300);
    const t2 = setTimeout(safeFit, 650);
    return () => { cancelled = true; clearTimeout(t1); clearTimeout(t2); };
  }, [elements.length, layout]);

  // Apply the Decision-pathways highlight. Runs when viewMode flips to
  // "pathways" (or the case data changes). Uses Cytoscape's dijkstra to
  // walk from the failing entity to each impact program AND each proposed
  // swap candidate, then paints those paths and dims everything else. The
  // amber hidden-dep highlight (managed by the next effect) layers on top
  // so the proposed-swap chain stays visually distinct from the at-risk
  // program chains. Clears on flip back to "network".
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    // Clear pathway-mode classes before deciding what to apply this pass.
    cy.elements().removeClass(
      "cy-impact-path cy-proposed-path cy-context-path cy-pathway-dim " +
      "cy-pathway-terminal cy-pathway-failing cy-pathway-edge-reverse",
    );
    // Restore any node + edge labels we mutated in the previous pass so
    // the Network tab reads normally again.
    const previousLabels =
      (cy.scratch("_kfPathwayOriginalLabels") as Record<string, string>) || {};
    for (const [id, original] of Object.entries(previousLabels)) {
      const n = cy.getElementById(id);
      if (n && n.length > 0) n.data("label", original);
    }
    cy.scratch("_kfPathwayOriginalLabels", {});
    const previousEdgeLabels =
      (cy.scratch("_kfPathwayOriginalEdgeLabels") as Record<string, string>) || {};
    for (const [id, original] of Object.entries(previousEdgeLabels)) {
      const e = cy.getElementById(id);
      if (e && e.length > 0) e.data("label", original);
    }
    cy.scratch("_kfPathwayOriginalEdgeLabels", {});

    if (viewMode !== "pathways" || !decisionSupport?.failing) {
      pathwayRetriesRef.current = 0;
      return;
    }
    const failingId = decisionSupport.failing.entityId;
    const failingNode = cy.getElementById(failingId);
    // When the modal first opens with initialViewMode="pathways" via the
    // post-revision deep-link, this effect can run before cytoscape has
    // finished ingesting the async-fetched elements. If the failing node
    // isn't there yet, schedule a single retry on the next paint frame —
    // by then cytoscape has caught up. Capped at 6 retries to avoid an
    // unbounded loop if the failing node truly isn't in the subgraph.
    if (!failingNode || failingNode.length === 0) {
      if (pathwayRetriesRef.current >= 6) return;
      pathwayRetriesRef.current += 1;
      const t = setTimeout(() => setCyReadyTick((n) => n + 1), 120);
      return () => clearTimeout(t);
    }
    pathwayRetriesRef.current = 0;
    const dijkstra = cy.elements().dijkstra({ root: failingNode });
    const keep = cy.collection();
    keep.merge(failingNode);
    const newOriginalLabels: Record<string, string> = {};
    // Per-node step number along its pathway (failing = 1; intermediate
    // buyers = 2; POs = 3; SKUs = 4; terminals = 5 for the typical
    // SUPPLIER → BUYER → PO → SKU → PROGRAM walk). When a node sits on
    // multiple pathways, the LOWEST step wins (a node "closer to the
    // start" reads more naturally as that step). Failing node always
    // pinned to 1 since it's the root of every dijkstra.
    const nodeStep: Record<string, number> = { [failingId]: 1 };
    const nodeCategory: Record<string, "failing" | "impact" | "proposed" | "context"> = {
      [failingId]: "failing",
    };
    const terminalIds = new Set<string>();

    // RECOMMENDED swap candidates — GREEN treatment. These have NO
    // surfaced concerns and are the pathways the reviewer should approve.
    decisionSupport.recommended.forEach((rec) => {
      const target = cy.getElementById(rec.entityId);
      if (!target || target.length === 0) return;
      const path = dijkstra.pathTo(target);
      if (path.length === 0) return;
      path.edges().addClass("cy-proposed-path");
      keep.merge(path);
      terminalIds.add(rec.entityId);
      path.nodes().forEach((node: any, i: number) => {
        const id = node.id();
        const step = i + 1;
        if (nodeStep[id] === undefined || step < nodeStep[id]) {
          nodeStep[id] = step;
        }
        if (!nodeCategory[id]) nodeCategory[id] = "proposed";
      });
    });

    // NOT-RECOMMENDED swap candidates — RED treatment. These have one or
    // more surfaced concerns (lapsed qualification, shared parent, etc.)
    // and should be rejected by the reviewer.
    decisionSupport.notRecommended.forEach((nr) => {
      const target = cy.getElementById(nr.entityId);
      if (!target || target.length === 0) return;
      const path = dijkstra.pathTo(target);
      if (path.length === 0) return;
      path.edges().addClass("cy-impact-path");
      keep.merge(path);
      terminalIds.add(nr.entityId);
      path.nodes().forEach((node: any, i: number) => {
        const id = node.id();
        const step = i + 1;
        if (nodeStep[id] === undefined || step < nodeStep[id]) {
          nodeStep[id] = step;
        }
        // not-recommended (red/impact) overrides only un-set; failing and
        // proposed (green) both stay since they're more specific.
        if (!nodeCategory[id]) nodeCategory[id] = "impact";
      });
    });

    // AT-RISK programs — SLATE treatment (cy-context-path). These aren't
    // supplier choices; they're the business stake the decision is
    // protecting. Rendered on the graph so the reviewer sees the full
    // context — failing supplier on the left, RECOMMENDED + AVOID
    // candidates in the middle, AT-RISK programs flowing out via the
    // tier-1 buyers and PO chains. Lowest category priority so a node
    // that lands on a recommended/avoid path keeps that color.
    decisionSupport.impacts.forEach((impact) => {
      const target = cy.getElementById(impact.entityId);
      if (!target || target.length === 0) return;
      const path = dijkstra.pathTo(target);
      if (path.length === 0) return;
      path.edges().addClass("cy-context-path");
      keep.merge(path);
      terminalIds.add(impact.entityId);
      path.nodes().forEach((node: any, i: number) => {
        const id = node.id();
        const step = i + 1;
        if (nodeStep[id] === undefined || step < nodeStep[id]) {
          nodeStep[id] = step;
        }
        if (!nodeCategory[id]) nodeCategory[id] = "context";
      });
    });

    // Apply per-node label prefix + category class. The prefix gives the
    // reviewer a strict reading order (1 → 2 → 3 → …) regardless of which
    // way the underlying cypher arrows point. Terminal nodes also get a
    // second-line WHY:
    //   • Recommended (green) terminals show the positive attributes
    //     ("✓ qualified · reliability 0.91") so the reviewer can see at a
    //     glance WHY this candidate is the right pick.
    //   • Not-recommended (red) terminals show the concerns
    //     ("⚠ qual lapsed 2026-04-15 · shared parent") so the reviewer
    //     sees WHY this candidate should be rejected.
    const recommendedByEntity = new Map(
      decisionSupport.recommended.map((p) => [p.entityId, p]),
    );
    const notRecommendedByEntity = new Map(
      decisionSupport.notRecommended.map((p) => [p.entityId, p]),
    );
    const impactsByEntity = new Map(
      decisionSupport.impacts.map((p) => [p.entityId, p]),
    );
    for (const [id, step] of Object.entries(nodeStep)) {
      const node = cy.getElementById(id);
      if (!node || node.length === 0) continue;
      const original = node.data("label") as string;
      newOriginalLabels[id] = original;
      let labelText = `${step} · ${original}`;
      if (terminalIds.has(id)) {
        const cat = nodeCategory[id];
        if (cat === "proposed") {
          const rec = recommendedByEntity.get(id);
          if (rec?.positives && rec.positives.length > 0) {
            labelText = `${labelText}\n✓ ${rec.positives.join(" · ")}`;
          }
        } else if (cat === "impact") {
          const nr = notRecommendedByEntity.get(id);
          if (nr?.concerns && nr.concerns.length > 0) {
            labelText = `${labelText}\n⚠ ${compactProposedConcerns(nr.concerns)}`;
          }
        } else if (cat === "context") {
          const ctx = impactsByEntity.get(id);
          if (ctx?.stake) {
            labelText = `${labelText}\n${compactImpactStake(ctx.stake)}`;
          }
        }
      }
      node.data("label", labelText);
      const cat = nodeCategory[id];
      if (cat === "failing") node.addClass("cy-pathway-failing");
      else if (cat === "proposed") node.addClass("cy-proposed-path");
      else if (cat === "impact") node.addClass("cy-impact-path");
      else if (cat === "context") node.addClass("cy-context-path");
      if (terminalIds.has(id)) node.addClass("cy-pathway-terminal");
    }

    // Pathway view = DECISION graph (not cypher graph). For every pathway
    // edge whose cypher source sits at a HIGHER step than its target, we
    // tag it with cy-pathway-edge-reverse so the visible arrow flips to
    // point from the low-step end to the high-step end. The reviewer's eye
    // can then follow the colored chain in step order without ever having
    // to walk against an arrow. The cypher-relationship label is also
    // rewritten to a flow-of-risk story phrase ("supplies", "placed
    // order", "delivered to", ...) so the edge text reads as a verb in
    // the flow direction rather than a graph-query type.
    const newOriginalEdgeLabels: Record<string, string> = {};
    cy.edges(".cy-impact-path, .cy-proposed-path").forEach((edge: any) => {
      const srcStep = nodeStep[edge.source().id()];
      const tgtStep = nodeStep[edge.target().id()];
      const reversed =
        srcStep !== undefined && tgtStep !== undefined && srcStep > tgtStep;
      if (reversed) edge.addClass("cy-pathway-edge-reverse");
      const cypherLabel = (edge.data("label") as string) || "";
      newOriginalEdgeLabels[edge.id()] = cypherLabel;
      edge.data("label", pathwayEdgeStory(cypherLabel, reversed));
    });
    cy.scratch("_kfPathwayOriginalEdgeLabels", newOriginalEdgeLabels);

    cy.scratch("_kfPathwayOriginalLabels", newOriginalLabels);
    // Hide every element NOT on a highlighted pathway. cy-pathway-dim now
    // sets display:none in the stylesheet so the canvas shows ONLY the
    // decision chains. Re-fit so the visible subset uses the whole canvas
    // (otherwise the pathways look lost in empty space left by the hidden
    // off-pathway nodes).
    cy.elements().difference(keep).addClass("cy-pathway-dim");
    setTimeout(() => {
      try { cy.fit(cy.elements(":visible"), 40); } catch { /* swallow */ }
    }, 50);
  }, [viewMode, decisionSupport, elements.length, layout, cyReadyTick]);

  // Pathway detail card is only meaningful on the Decision pathways tab —
  // dismiss it the moment the user flips to Network so the legend doesn't
  // hold a stale reveal.
  useEffect(() => {
    if (viewMode !== "pathways") setPathwayDetail(null);
  }, [viewMode]);

  // When the user flips back to the Network tab, re-fit to ALL elements
  // so the wider graph isn't stranded off-screen at the pathway-zoom.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || viewMode !== "network") return;
    const t = setTimeout(() => {
      try { cy.fit(undefined, 40); } catch { /* swallow */ }
    }, 50);
    return () => clearTimeout(t);
  }, [viewMode]);

  // Apply the hidden-dependency path highlight. Runs after the elements
  // collection settles (and re-runs when the path list changes). Adds the
  // .cy-hidden-dep-path class to every matching node and every edge whose
  // two endpoints are both in the highlighted set. Doesn't dim the rest of
  // the graph — the user keeps full freedom to click-explore; the amber
  // chain just glows against the default palette.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass("cy-hidden-dep-path");
    const ids = (hiddenDepPath ?? []).filter(Boolean);
    if (ids.length === 0) return;
    const targetNodes = cy.collection();
    for (const id of ids) {
      const n = cy.getElementById(id);
      if (n.length) targetNodes.merge(n);
    }
    if (targetNodes.length === 0) return;
    targetNodes.addClass("cy-hidden-dep-path");
    targetNodes.connectedEdges().forEach((edge: any) => {
      if (
        edge.source().hasClass("cy-hidden-dep-path") &&
        edge.target().hasClass("cy-hidden-dep-path")
      ) {
        edge.addClass("cy-hidden-dep-path");
      }
    });
  }, [hiddenDepPath, elements.length, layout]);

  // Double-click any colored pathway node to surface the downstream
  // program exposure in the side legend. Uses a manual lastTap-timing
  // detector (same pattern as attachEvidenceMapBehaviour) instead of
  // cytoscape's dbltap event — the dbltap was being eaten by the
  // pre-attached tap handlers in attachEvidenceMapBehaviour, so the
  // listener never fired. Single-click still runs the existing
  // fact-reveal handler — this is additive, not replacing.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    if (viewMode !== "pathways") return;
    if (!decisionSupport) return;
    const allPrograms = decisionSupport.impacts ?? [];
    const lastTap = { id: "", time: 0 };
    const handler = (evt: any) => {
      const target = evt.target;
      if (!target || typeof target.id !== "function") return;
      const nodeIdNow = target.id();
      const t = (window.performance || Date).now();
      const isDouble =
        lastTap.id === nodeIdNow && t - lastTap.time < 400;
      lastTap.id = isDouble ? "" : nodeIdNow;
      lastTap.time = isDouble ? 0 : t;
      if (!isDouble) return;
      const cls: string[] = (target.classes() as string[]) || [];
      const isFailing = cls.includes("cy-pathway-failing");
      const isProposed = cls.includes("cy-proposed-path");
      const isAvoid = cls.includes("cy-impact-path");
      const isImpact = cls.includes("cy-context-path");
      if (!isFailing && !isProposed && !isAvoid && !isImpact) return;
      // Failing supplier or a supplier-swap chain (green or red) →
      // ALL programs affected (the swap pick is upstream of every
      // impact chain).
      if (isFailing) {
        setPathwayDetail({
          variant: "failing",
          triggerLabel: target.data("label") || target.id(),
          programs: allPrograms,
        });
        return;
      }
      if (isProposed) {
        setPathwayDetail({
          variant: "proposed",
          triggerLabel: target.data("label") || target.id(),
          programs: allPrograms,
        });
        return;
      }
      if (isAvoid) {
        setPathwayDetail({
          variant: "avoid",
          triggerLabel: target.data("label") || target.id(),
          programs: allPrograms,
        });
        return;
      }
      // Slate impact chain — find the specific program(s) this node
      // sits on the path to. If the node IS a program terminal, just
      // show that program; otherwise walk forward to find the
      // terminal(s) reachable through cy-context-path edges.
      const nodeId = target.id();
      const direct = allPrograms.find((p) => p.entityId === nodeId);
      if (direct) {
        setPathwayDetail({
          variant: "impact",
          triggerLabel: target.data("label") || nodeId,
          programs: [direct],
        });
        return;
      }
      // Walk along cy-context-path edges from this node to find the
      // terminal program(s). Use cytoscape's dijkstra to test
      // reachability to each program's entityId.
      const reachable: DecisionPath[] = [];
      for (const p of allPrograms) {
        const dest = cy.getElementById(p.entityId);
        if (!dest || dest.length === 0) continue;
        const dij = cy
          .elements(".cy-context-path, .cy-pathway-failing")
          .dijkstra({ root: target });
        const path = dij.pathTo(dest);
        if (path && path.length > 0) reachable.push(p);
      }
      setPathwayDetail({
        variant: "impact",
        triggerLabel: target.data("label") || nodeId,
        programs: reachable.length > 0 ? reachable : allPrograms,
      });
    };
    cy.on("tap", "node", handler);
    return () => {
      cy.removeListener("tap", "node", handler);
    };
  }, [viewMode, decisionSupport, elements.length, cyReadyTick]);

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
        {/* View-mode tabs — Network is the clean overview; Decision pathways
            overlays per-pathway highlights using the case's decisionSupport
            data. The Pathways tab is disabled when the case has no proposed
            or at-risk pathways to highlight (e.g. simpler onboarding cases). */}
        <div className="graph-modal-tabs">
          <button
            type="button"
            className={`graph-modal-tab${viewMode === "network" ? " active" : ""}`}
            onClick={() => setViewMode("network")}
          >
            Network
          </button>
          <button
            type="button"
            className={`graph-modal-tab${viewMode === "pathways" ? " active" : ""}`}
            onClick={() => setViewMode("pathways")}
            disabled={!decisionSupport}
            title={
              decisionSupport
                ? "Highlight the proposed swap pathway + at-risk program pathways; dim everything else."
                : "This case has no proposed or at-risk pathways to highlight."
            }
          >
            Decision pathways
            {decisionSupport && (
              <span className="graph-modal-tab-count">
                {decisionSupport.recommended.length +
                 decisionSupport.notRecommended.length +
                 decisionSupport.impacts.length}
              </span>
            )}
          </button>
        </div>
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
                  // react-cytoscapejs fires this callback on EVERY render
                  // (componentDidUpdate), not just on first mount. Guard
                  // so the side effects + setCyReadyTick only run when
                  // we get a genuinely new cy instance — otherwise the
                  // setState here triggers a render → which fires this
                  // callback again → infinite loop (React's "Maximum
                  // update depth exceeded").
                  if (cyRef.current === cy) return;
                  cyRef.current = cy;
                  // Tell every cy-dependent effect that the ref is now
                  // populated. One bump per cytoscape instance.
                  setCyReadyTick((n) => n + 1);
                  // Cap zoom so cy.fit() never enlarges nodes past their
                  // intrinsic size — without this, small dots cause the
                  // Editorial knowledge graph to zoom 4–5× in and the
                  // serif labels stack on top of each other.
                  cy.maxZoom(1.4);
                  cy.minZoom(0.2);
                  attachInteractivity(cy);
                  attachEvidenceMapBehaviour(cy, setSelectedClassFacts, onDrill ?? null, active ?? null);
                  attachEntityFactClickReveal(cy, active ?? null, setSelectedEntityFact);
                  // First-mount layout kick — fixes the "everything piled
                  // at (0,0)" first-open bug. Sequence on modal open:
                  //   1. Fetch resolves, elements transition 0 → N
                  //   2. The layout useEffect fires, bails at `if (!cy)`
                  //      because react-cytoscapejs hasn't called us yet
                  //   3. THEN this callback fires and sets cyRef
                  //   4. The useEffect never re-runs because its deps
                  //      [elements.length, layout] didn't change
                  // So nothing ever lays out the graph. We fix that by
                  // running the layout right here on first attach when
                  // elements are already present. Scratch flag makes it
                  // idempotent against re-invocation of the cy callback.
                  if (!cy.scratch("_kfInitLayoutDone") && cy.elements().length > 0) {
                    cy.scratch("_kfInitLayoutDone", true);
                    try {
                      const l = cy.layout(layoutOptions(layout));
                      l.on("layoutstop", () => {
                        try { cy.fit(undefined, 40); } catch { /* swallow */ }
                      });
                      l.run();
                      // Belt-and-braces fit timers in case layoutstop fires
                      // before the canvas finished sizing.
                      setTimeout(() => { try { cy.fit(undefined, 40); } catch {} }, 300);
                      setTimeout(() => { try { cy.fit(undefined, 40); } catch {} }, 650);
                    } catch (e) {
                      console.warn("Initial layout failed:", e);
                    }
                  }
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
            explainer={explainer}
            selectedClassFacts={selectedClassFacts}
            onDismissFacts={() => setSelectedClassFacts(null)}
            drillHint={
              variant === "evidence" && active && DRILL_HANDLERS.neo4j.available(active)
                ? DRILL_HANDLERS.neo4j.hint
                : null
            }
            selectedEntityFact={selectedEntityFact}
            onDismissEntityFact={() => setSelectedEntityFact(null)}
            decisionSupport={viewMode === "pathways" ? decisionSupport : null}
            pathwayDetail={viewMode === "pathways" ? pathwayDetail : null}
            onDismissPathwayDetail={() => setPathwayDetail(null)}
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
  explainer,
  selectedClassFacts,
  onDismissFacts,
  drillHint,
  selectedEntityFact,
  onDismissEntityFact,
  decisionSupport,
  pathwayDetail,
  onDismissPathwayDetail,
}: {
  open: boolean;
  onToggle: () => void;
  variant: "knowledge" | "evidence";
  typeCounts: { type: string; count: number }[];
  subtitle?: string;
  explainer?: string;
  selectedClassFacts?: SelectedClassFacts | null;
  onDismissFacts?: () => void;
  drillHint?: string | null;
  selectedEntityFact?: EntityFactReveal | null;
  onDismissEntityFact?: () => void;
  decisionSupport?: DecisionSupport | null;
  pathwayDetail?: {
    variant: "proposed" | "avoid" | "impact" | "failing";
    triggerLabel: string;
    programs: DecisionPath[];
  } | null;
  onDismissPathwayDetail?: () => void;
}) {
  return (
    <aside className={`graph-modal-side-legend${open ? "" : " collapsed"}`}>
      <button type="button" className="graph-modal-side-legend-toggle" onClick={onToggle}>
        <span>LEGEND</span>
        <span aria-hidden="true">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="graph-modal-side-legend-body">
          {/* Pathway-impact reveal — surfaces the moment the user double-
              clicks a colored chain. Sits at the very top so it's the
              first thing they see when they ask the question. */}
          {pathwayDetail && (
            <PathwayImpactCard
              detail={pathwayDetail}
              onDismiss={onDismissPathwayDetail ?? (() => {})}
            />
          )}
          {/* Decision-support panel sits at the very top — it's the most
              decision-relevant content. Renders ONLY when the case actually
              has proposed or at-risk pathways to summarise (otherwise the
              panel returns null and nothing is added to the legend). */}
          {decisionSupport && <DecisionSupportPanel support={decisionSupport} />}
          {explainer && (
            <div className="graph-modal-side-legend-explainer">{explainer}</div>
          )}
          {subtitle && <div className="graph-modal-side-legend-subtitle">{subtitle}</div>}
          {/* Pinned at the top of the legend whenever a node has been tapped
              and matched to a case fact. The card shows what that node is
              "saying" inside the stages — role pill, hidden-dep callout,
              summary chips — so the user can read the evidence without
              closing the modal. Dismisses cleanly when a non-matching node
              or the background is tapped. */}
          {selectedEntityFact && (
            <EntityFactRevealCard
              reveal={selectedEntityFact}
              onDismiss={onDismissEntityFact ?? (() => {})}
            />
          )}
          {!selectedEntityFact && variant === "knowledge" && !pathwayDetail && (
            <div className="graph-modal-side-legend-tip">
              <strong>Tip ·</strong> click any node to see its card from the
              stages.
              {decisionSupport && (
                <>
                  {" "}On the Decision-pathways tab,{" "}
                  <strong>double-click</strong> a colored chain to see the
                  downstream programs it protects (green) or leaves exposed
                  (red).
                </>
              )}
            </div>
          )}
          {selectedClassFacts && (
            <ClassDetailsPanel
              className={selectedClassFacts.className}
              ontologyId={selectedClassFacts.ontologyId}
              onDismiss={onDismissFacts}
            />
          )}
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
                      {variant === "evidence" && (
                        <button
                          type="button"
                          className="graph-modal-side-legend-info"
                          title={`Open the ${tc.type} class spec`}
                          onClick={() =>
                            window.dispatchEvent(
                              new CustomEvent("open-case-spec", {
                                detail: { tab: "ontology", anchor: `spec-class-${tc.type}` },
                              }),
                            )
                          }
                        >ⓘ</button>
                      )}
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

// ---------------------------------------------------------------------------
// Pathway palette — two semantic colours only so the reviewer's eye doesn't
// have to learn a 5-colour key:
//   • GREEN — proposed pathway (a swap candidate)
//   • RED   — at-risk pathway (a program / SKU / buyer at stake)
// Multiple pathways in the same category are disambiguated by a numbered
// terminal-node label ("1 · Stillwater Alloys", "1 · Mirage Avionics",
// etc.) — the number cross-references the side-panel order.
// ---------------------------------------------------------------------------
const PROPOSED_PATH_COLOR = "#16a34a"; // green
const IMPACT_PATH_COLOR = "#c14a4a";   // red

// Compact-for-graph helpers — used to append the WHY (stake or
// concerns) to a terminal node's label without overflowing the
// 110px text-max-width set in the knowledge stylesheet.
function compactImpactStake(stake: string): string {
  // "$48M revenue · $220k/day OTD penalty" → "$48M · $220k/day"
  return stake
    .replace(/ revenue at risk/g, "")
    .replace(/ revenue/g, "")
    .replace(/ OTD penalty/g, "")
    .replace(/\s+·\s+/g, " · ");
}

function compactProposedConcerns(concerns: string[]): string {
  // Map known phrases to short tags so the suffix fits on a second line.
  return concerns
    .map((c) => {
      const lower = c.toLowerCase();
      if (lower.includes("qualification") || lower.includes("certification")) {
        const expM = c.match(/expired ([0-9-]+)/);
        return expM ? `qual lapsed ${expM[1]}` : "qual lapsed";
      }
      if (lower.includes("shared parent")) return "shared parent";
      if (lower.includes("authority")) return "above authority";
      return c.length > 32 ? c.substring(0, 29) + "…" : c;
    })
    .join(" · ");
}

// Cypher relationship → story-of-risk-flow label rewrite for the
// Pathways tab. The 2nd arg flags edges whose cypher direction is
// opposite to the path-step direction (so the visible arrow was
// flipped via cy-pathway-edge-reverse); the verb tense changes
// accordingly. Default: lowercase the cypher type with spaces.
function pathwayEdgeStory(cypherLabel: string, reversed: boolean): string {
  switch (cypherLabel) {
    case "SOURCES_FROM":      return reversed ? "supplies" : "buys from";
    case "PLACED":            return "placed order";
    case "CONTAINS":          return "for SKU";
    case "INCLUDED_IN":       return "delivered to";
    case "CONTROLLED_BY":     return reversed ? "also owns" : "owned by";
    case "OWNS_SHARE":        return "owns share in";
    case "PARENT_OF":         return reversed ? "subsidiary of" : "parent of";
    case "JOINT_VENTURE_WITH":return "JV partner";
    case "SHIPS_VIA":         return "ships via";
    case "MEMBER_OF":         return "member of";
    default:                  return cypherLabel.toLowerCase().replace(/_/g, " ");
  }
}

// ---------------------------------------------------------------------------
// Decision support — walks the case's facts and groups them into the
// pathways the reviewer is being asked to evaluate. Surfaces:
//   • the failing entity that triggered the case (FAILING)
//   • each proposed swap pathway with its concerns parsed from the summary
//   • each at-risk pathway with the business stake parsed from the summary
//   • an inferred recommendation if every proposed swap has concerns
// Renders ONLY in the side legend — the graph itself stays uncluttered.
// ---------------------------------------------------------------------------
interface DecisionPath {
  entityId: string;
  entityName: string;
  viaPath?: string;
  hops?: number;
  concerns?: string[];   // populated on not-recommended candidates only
  positives?: string[];  // populated on recommended candidates only
  stake?: string;        // populated on impact entries only
}

interface DecisionSupport {
  // Swap candidates with NO concerns surfaced — what the reviewer should
  // most likely pick. Rendered GREEN in the graph + side panel.
  recommended: DecisionPath[];
  // Swap candidates WITH concerns (lapsed qualification, shared parent,
  // above-authority risk, etc.) — what the reviewer should reject. RED.
  notRecommended: DecisionPath[];
  // Programs whose SKUs are exposed if no swap happens. Surfaced in the
  // side panel as CONTEXT ("here's what's at stake") but NOT drawn on
  // the pathways graph — they aren't supplier choices.
  impacts: DecisionPath[];
  failing?: { entityId: string; entityName: string; statusLabel: string };
  recommendation?: string;
}

function _humanizeViaPathForSupport(vp: string): string {
  if (vp === "joint-venture partner") return "a joint-venture partnership";
  if (vp.startsWith("sibling via parent ")) {
    return vp.replace("sibling via parent ", "") + " (shared parent)";
  }
  if (vp.startsWith("sibling via ")) {
    return vp.replace(/^sibling via /, "").replace(/\s+\(HoldingCompany\)$/, "");
  }
  return vp;
}

function computeDecisionSupport(active: CaseFull | null): DecisionSupport | null {
  if (!active?.stages) return null;
  const recommended: DecisionPath[] = [];
  const notRecommended: DecisionPath[] = [];
  const impacts: DecisionPath[] = [];
  let failing: DecisionSupport["failing"];

  // W1 / Beat 3 — pre-scan for "new evidence" facts injected by /revise
  // triggers. These reclassify previously-recommended alternatives into
  // not-recommended ones. Each fact carries a SUP-id in its title; we
  // match against AlternativeSupplier entity ids below.
  //
  // Supported new-evidence fact types:
  //   • QualificationUpdate · status: "lapsed" → flips the matched
  //     candidate to NOT recommended with a "qualification lapsed" concern
  //   • SanctionsProximity (new SDN listing) → flips the matched
  //     candidate to NOT recommended with a "fresh SDN exposure" concern
  const evidenceConcernsByEntity = new Map<string, string[]>();
  const SUP_ID_RE = /\bSUP-\d+\b/;
  for (const stage of active.stages) {
    for (const fact of stage.facts ?? []) {
      // Qualification update — title format: "Ironcrest Metalworks (SUP-023) · qualification lapsed"
      if (
        fact.ontology_type === "QualificationUpdate" &&
        typeof fact.status === "string" &&
        fact.status === "lapsed"
      ) {
        const m = fact.title?.match(SUP_ID_RE);
        if (m) {
          const list = evidenceConcernsByEntity.get(m[0]) ?? [];
          list.push("Quality certification lapsed (new evidence)");
          evidenceConcernsByEntity.set(m[0], list);
        }
      }
      // Fresh SDN listing — SanctionsProximity facts injected POST-decision
      // that name a supplier id in the summary. The original-run
      // SanctionsProximity facts named SDNs in title, not suppliers, so
      // we only catch the injected ones.
      if (
        fact.ontology_type === "SanctionsProximity" &&
        typeof fact.summary === "string"
      ) {
        const m = fact.summary?.match(SUP_ID_RE);
        if (m) {
          const list = evidenceConcernsByEntity.get(m[0]) ?? [];
          list.push("Fresh OFAC SDN exposure surfaced (new evidence)");
          evidenceConcernsByEntity.set(m[0], list);
        }
        // Also catch by title (e.g. "Vega Marine Trading (OFAC SDN)" with
        // summary mentioning "Ironcrest"). Look for SUP-XXX in summary.
      }
    }
  }

  for (const stage of active.stages) {
    for (const fact of stage.facts ?? []) {
      // FAILING supplier — the trigger node
      if (
        fact.ontology_type === "Supplier" &&
        typeof fact.status === "string" &&
        fact.status.startsWith("chapter_11")
      ) {
        const m = fact.status.match(/^chapter_11_filed_(\d{4}-\d{2}-\d{2})$/);
        failing = {
          entityId: fact.id,
          entityName: fact.title ?? fact.id,
          statusLabel: m ? `Chapter 11 filed · ${m[1]}` : fact.status,
        };
        continue;
      }
      // SWAP CANDIDATE — classify into recommended vs not-recommended based
      // on the concerns surfaced from the summary + via_path. Concerns
      // observed today:
      //   • qualification: lapsed (quality cert expired)
      //   • shared HoldingCompany (concentration risk unchanged)
      //   • shared parent supplier (same)
      // A candidate with ZERO concerns is recommended (green). Any
      // candidate with one or more concerns is NOT recommended (red).
      if (fact.ontology_type === "AlternativeSupplier") {
        const sum = fact.summary ?? "";
        const concerns: string[] = [];
        const qm = sum.match(/qualification: (lapsed)( \(expired ([0-9-]+)\))?/);
        if (qm) {
          concerns.push(
            qm[3]
              ? `Quality certification lapsed (expired ${qm[3]})`
              : "Quality certification lapsed",
          );
        }
        if (fact.via_path && fact.via_path.includes("HoldingCompany")) {
          concerns.push(
            "Shared parent with failing supplier — concentration risk unchanged",
          );
        } else if (
          fact.via_path &&
          fact.via_path.startsWith("sibling via parent")
        ) {
          concerns.push(
            "Shared parent supplier — concentration risk unchanged",
          );
        }
        // W1 / Beat 3 — fold any new-evidence concerns into this
        // candidate's concern list. Looks the candidate up by its SUP-id
        // in the pre-scanned map. After this, a previously-recommended
        // (no concerns) candidate that received new evidence will move
        // to the not-recommended pile below.
        const evidenceConcerns = evidenceConcernsByEntity.get(fact.id) ?? [];
        for (const ec of evidenceConcerns) {
          if (!concerns.includes(ec)) concerns.push(ec);
        }
        // Positive attributes parsed from the summary for recommended
        // candidates — qualification status, reliability score, and the
        // graph-walk path that surfaced them. Drives the "✓ qualified ·
        // reliability 0.91" terminal label.
        const positives: string[] = [];
        if (sum.match(/qualification: qualified/)) {
          positives.push("qualified");
        }
        const relMatch = sum.match(/reliability ([0-9.]+)/);
        if (relMatch) positives.push(`reliability ${relMatch[1]}`);
        if (fact.via_path === "joint-venture partner") {
          positives.push("JV partner");
        }

        const candidate: DecisionPath = {
          entityId: fact.id,
          entityName: fact.title ?? fact.id,
          viaPath: fact.via_path
            ? _humanizeViaPathForSupport(fact.via_path)
            : undefined,
          hops: typeof fact.hops === "number" ? fact.hops : undefined,
          concerns: concerns.length > 0 ? concerns : undefined,
          positives: positives.length > 0 ? positives : undefined,
        };
        if (concerns.length === 0) {
          recommended.push(candidate);
        } else {
          notRecommended.push(candidate);
        }
        continue;
      }
      // AT-RISK program — surfaced as side-panel context (not on graph)
      if (fact.ontology_type === "ProgramImpact") {
        const sum = fact.summary ?? "";
        const stakeMatch = sum.match(/\$([0-9.]+M)\s*revenue at risk(?:\s*·\s*\$([0-9.]+k)\/day OTD penalty)?/);
        const viaMatch = sum.match(/via\s+([^·]+?)\s+·/);
        let stake: string | undefined;
        if (stakeMatch) {
          stake = stakeMatch[2]
            ? `$${stakeMatch[1]} revenue · $${stakeMatch[2]}/day OTD penalty`
            : `$${stakeMatch[1]} revenue at risk`;
        }
        impacts.push({
          entityId: fact.id,
          entityName: fact.title ?? fact.id,
          viaPath: viaMatch ? viaMatch[1].trim() : undefined,
          stake,
        });
      }
    }
  }

  if (
    recommended.length === 0 &&
    notRecommended.length === 0 &&
    impacts.length === 0 &&
    !failing
  ) {
    return null;
  }

  // Recommendation text — drives the bottom of the side panel.
  let recommendation: string | undefined;
  if (recommended.length > 0 && notRecommended.length > 0) {
    recommendation =
      `Recommend swap to ${recommended[0].entityName}. Avoid ${notRecommended[0].entityName} — the listed concerns make it ineligible.`;
  } else if (recommended.length > 0) {
    recommendation =
      `Recommend swap to ${recommended[0].entityName} — no governance concerns surfaced.`;
  } else if (notRecommended.length > 0) {
    recommendation =
      "No clean swap candidates surfaced. Every graph-matched alternative has governance concerns — consider REQUEST MORE INFO or extended search.";
  }

  return { recommended, notRecommended, impacts, failing, recommendation };
}

// W2 / Beat 1 — pathway-impact reveal. Lands at the top of the side
// legend when the user double-clicks a colored chain. Same shell for
// all four variants; the eyebrow + verb adapt to the framing:
//   • proposed (green)  — "Programs protected by this pick"
//   • avoid (red)       — "Programs still exposed if you picked this"
//   • failing           — "Programs at stake — every chain runs through here"
//   • impact (slate)    — "Programs reached via this chain"
function PathwayImpactCard({
  detail,
  onDismiss,
}: {
  detail: {
    variant: "proposed" | "avoid" | "impact" | "failing";
    triggerLabel: string;
    programs: DecisionPath[];
  };
  onDismiss: () => void;
}) {
  const variantInfo: Record<
    typeof detail.variant,
    { className: string; eyebrow: string; verb: string; lead: string }
  > = {
    proposed: {
      className: "pathway-impact-card-proposed",
      eyebrow: "Programs protected by this pick",
      verb: "Picking this pathway protects",
      lead: "Approving the swap to this candidate keeps every flagship-program SKU shipping — the JV's existing capacity absorbs Northwind's role across the three tier-1 buyers.",
    },
    avoid: {
      className: "pathway-impact-card-avoid",
      eyebrow: "Programs still exposed if you picked this",
      verb: "This pathway leaves exposed",
      lead: "Approving this alternate does NOT mitigate the exposure — the parent risk is unchanged and the lapsed qualification blocks shipments to flagship-program SKUs. Every program below remains at full stake.",
    },
    failing: {
      className: "pathway-impact-card-failing",
      eyebrow: "Programs at stake — every chain runs through here",
      verb: "Failure here exposes",
      lead: "This is the root of every at-risk chain. Without a successful swap, all three programs below see their full revenue + OTD-penalty exposure.",
    },
    impact: {
      className: "pathway-impact-card-impact",
      eyebrow: "Programs reached via this chain",
      verb: "This chain channels exposure to",
      lead: "The tier-1 buyer on this chain places POs that feed the program(s) below. If the failing supplier isn't swapped, the program SKUs miss their delivery window.",
    },
  };
  const info = variantInfo[detail.variant];

  // Parse "$48M revenue · $220k/day OTD penalty" into dollar figures so we
  // can total them up. Stake format is stable from the supply_chain ontology
  // mapping; if the regex doesn't match we just skip that program in the
  // total (the per-row text still renders).
  const parsed = detail.programs.map((p) => {
    const m = (p.stake || "").match(/\$([0-9.]+)M.*?\$([0-9.]+)k\/day/);
    return {
      ...p,
      revenueM: m ? parseFloat(m[1]) : 0,
      otdK: m ? parseFloat(m[2]) : 0,
    };
  });
  const totalRevM = parsed.reduce((acc, p) => acc + p.revenueM, 0);
  const totalOtdK = parsed.reduce((acc, p) => acc + p.otdK, 0);
  const hasTotals = totalRevM > 0;

  return (
    <div className={`pathway-impact-card ${info.className}`}>
      <div className="pathway-impact-card-head">
        <div className="pathway-impact-card-eyebrow">{info.eyebrow}</div>
        <button
          type="button"
          className="pathway-impact-card-dismiss"
          onClick={onDismiss}
          aria-label="Dismiss pathway detail"
        >
          ×
        </button>
      </div>
      <div className="pathway-impact-card-trigger">
        Double-clicked: <strong>{detail.triggerLabel}</strong>
      </div>
      <p className="pathway-impact-card-lead">{info.lead}</p>
      {parsed.length > 0 ? (
        <>
          <div className="pathway-impact-card-list-label">
            {info.verb}
          </div>
          <ul className="pathway-impact-card-list">
            {parsed.map((p) => (
              <li key={p.entityId}>
                <div className="pathway-impact-card-program">
                  {p.entityName}
                </div>
                {p.stake && (
                  <div className="pathway-impact-card-stake">{p.stake}</div>
                )}
                {p.viaPath && (
                  <div className="pathway-impact-card-via">
                    via {p.viaPath}
                  </div>
                )}
              </li>
            ))}
          </ul>
          {hasTotals && (
            <div className="pathway-impact-card-total">
              <span className="pathway-impact-card-total-label">Total</span>
              <span className="pathway-impact-card-total-value">
                ${totalRevM}M revenue · ${totalOtdK}k/day OTD penalty
              </span>
            </div>
          )}
        </>
      ) : (
        <div className="pathway-impact-card-empty">
          No program-impact chains attached to this node in the current
          case data.
        </div>
      )}
    </div>
  );
}

function DecisionSupportPanel({ support }: { support: DecisionSupport }) {
  return (
    <div className="decision-support">
      <div className="decision-support-eyebrow">Decision support</div>
      {support.failing && (
        <div className="decision-support-trigger">
          <span className="decision-support-trigger-marker" aria-hidden="true">⛔</span>
          <span>
            Triggered by{" "}
            <strong>{support.failing.entityName}</strong>
            <span className="decision-support-trigger-status">
              {" "}· {support.failing.statusLabel}
            </span>
          </span>
        </div>
      )}
      <div className="decision-support-reading-hint">
        Pathways tab shows the <strong>decision graph</strong>:
        {" "}<strong style={{ color: PROPOSED_PATH_COLOR }}>green</strong>{" "}
        = recommended swap (pick this);
        {" "}<strong style={{ color: IMPACT_PATH_COLOR }}>red</strong>{" "}
        = candidates to reject (severe concerns);
        {" "}<strong style={{ color: "#64748b" }}>slate</strong>{" "}
        = at-risk programs (business stake, context only);
        {" "}<strong style={{ color: "#000000" }}>■</strong> = failing
        supplier. Nodes numbered <strong>1 → N</strong> in flow order.
      </div>
      {support.recommended.length > 0 && (
        <div className="decision-support-section">
          <div className="decision-support-section-label">
            Recommended swap{support.recommended.length === 1 ? "" : "s"}
            <span className="decision-support-count">({support.recommended.length})</span>
          </div>
          {support.recommended.map((p, i) => (
            <div
              key={p.entityId}
              className="decision-support-path proposed"
              style={{ borderLeftColor: PROPOSED_PATH_COLOR }}
            >
              <div className="decision-support-path-header">
                <span
                  className="decision-support-path-marker"
                  style={{ background: PROPOSED_PATH_COLOR }}
                  title={`Green chain in the graph terminates at "${i + 1} · ${p.entityName}"`}
                >
                  {i + 1}
                </span>
                <span className="decision-support-path-name">{p.entityName}</span>
              </div>
              {p.viaPath && (
                <div className="decision-support-path-via">
                  via <strong>{p.viaPath}</strong>
                  {typeof p.hops === "number" && ` · ${p.hops}-hop chain`}
                </div>
              )}
              {p.positives && p.positives.length > 0 && (
                <ul className="decision-support-positives">
                  {p.positives.map((pos, j) => (
                    <li key={j}>{pos}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
      {support.notRecommended.length > 0 && (
        <div className="decision-support-section">
          <div className="decision-support-section-label">
            Avoid
            <span className="decision-support-count">({support.notRecommended.length})</span>
          </div>
          {support.notRecommended.map((p, i) => (
            <div
              key={p.entityId}
              className="decision-support-path impact"
              style={{ borderLeftColor: IMPACT_PATH_COLOR }}
            >
              <div className="decision-support-path-header">
                <span
                  className="decision-support-path-marker"
                  style={{ background: IMPACT_PATH_COLOR }}
                  title={`Red chain in the graph terminates at "${i + 1} · ${p.entityName}"`}
                >
                  {i + 1}
                </span>
                <span className="decision-support-path-name">{p.entityName}</span>
              </div>
              {p.viaPath && (
                <div className="decision-support-path-via">
                  via <strong>{p.viaPath}</strong>
                  {typeof p.hops === "number" && ` · ${p.hops}-hop chain`}
                </div>
              )}
              {p.concerns && p.concerns.length > 0 && (
                <ul className="decision-support-concerns">
                  {p.concerns.map((c, j) => (
                    <li key={j}>{c}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
      {support.impacts.length > 0 && (
        <div className="decision-support-section">
          <div className="decision-support-section-label">
            At-risk programs
            <span className="decision-support-count">({support.impacts.length})</span>
            <span className="decision-support-section-sublabel">— slate chains in graph, business stake only</span>
          </div>
          {support.impacts.map((p) => (
            <div
              key={p.entityId}
              className="decision-support-path context"
            >
              <div className="decision-support-path-header">
                <span className="decision-support-path-name">{p.entityName}</span>
              </div>
              {p.stake && (
                <div className="decision-support-path-stake">{p.stake}</div>
              )}
              {p.viaPath && (
                <div className="decision-support-path-via">via {p.viaPath}</div>
              )}
            </div>
          ))}
        </div>
      )}
      {support.recommendation && (
        <div className="decision-support-recommendation">
          {support.recommendation}
        </div>
      )}
    </div>
  );
}

// Mini fact reveal — what's shown in the side legend when a graph node is
// tapped and matches a case fact. Carries the same role pill + hidden-
// dependency callout vocabulary the Envelope uses, so the user sees a single
// consistent labelling system on both surfaces. Intentionally NOT a reuse of
// Envelope's FactCard because (a) cross-importing would introduce a module
// cycle and (b) the modal's side-panel space is much narrower than the
// envelope grid — a simpler chrome works better.
function EntityFactRevealCard({
  reveal,
  onDismiss,
}: {
  reveal: EntityFactReveal;
  onDismiss: () => void;
}) {
  const { fact, stageName } = reveal;
  // Same role + hidden-dep rules as Envelope.FactCard. Kept inline for
  // visual symmetry with the FactCard's source row.
  const role: { label: string; variant: string } | null = (() => {
    if (
      fact.ontology_type === "Supplier" &&
      typeof fact.status === "string" &&
      fact.status.startsWith("chapter_11")
    ) return { label: "FAILING", variant: "failing" };
    if (fact.ontology_type === "AlternativeSupplier")
      return { label: "PROPOSED ALT", variant: "proposed-alt" };
    if (fact.ontology_type === "DownstreamDependent")
      return { label: "AFFECTED BUYER", variant: "affected-buyer" };
    if (fact.ontology_type === "ProgramImpact")
      return { label: "AT-RISK PROGRAM", variant: "at-risk-program" };
    return null;
  })();
  const tierDepth = typeof fact.tier === "number" ? fact.tier : null;
  const hopDepth = typeof fact.hops === "number" ? fact.hops : null;
  const isHiddenDep =
    (tierDepth !== null && tierDepth >= 2) ||
    (hopDepth !== null && hopDepth >= 2);
  const humanizeViaPath = (vp: string): string => {
    if (vp === "joint-venture partner") return "a joint-venture partnership";
    if (vp.startsWith("sibling via parent ")) {
      return vp.replace("sibling via parent ", "") + " (shared parent)";
    }
    if (vp.startsWith("sibling via ")) {
      return vp
        .replace(/^sibling via /, "")
        .replace(/\s+\(HoldingCompany\)$/, "");
    }
    return vp;
  };
  const chips = (fact.summary || "")
    .split(/\s+·\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
  return (
    <div className="entity-fact-reveal">
      <div className="entity-fact-reveal-eyebrow">
        <span>Card from stage · {stageName}</span>
        <button
          type="button"
          className="entity-fact-reveal-dismiss"
          onClick={onDismiss}
          aria-label="Clear selection"
        >×</button>
      </div>
      <div className="entity-fact-reveal-meta">
        <span className="entity-fact-reveal-id">{fact.id}</span>
        <span className="entity-fact-reveal-class">{fact.ontology_type}</span>
        {role && (
          <span className={`fact-role-pill fact-role-${role.variant}`}>
            {role.label}
          </span>
        )}
      </div>
      <div className="entity-fact-reveal-title">{fact.title}</div>
      {isHiddenDep && (
        <div className="entity-fact-reveal-hidden-dep">
          <span aria-hidden="true">⚠</span>{" "}
          <strong>Hidden dependency</strong>
          {" · "}
          {tierDepth !== null && tierDepth >= 2 ? (
            <>tier-{tierDepth} supplier — upstream chain</>
          ) : fact.via_path ? (
            <>{hopDepth}-hop chain via <strong>{humanizeViaPath(fact.via_path)}</strong></>
          ) : (
            <>{hopDepth}-hop relationship chain</>
          )}
        </div>
      )}
      {chips.length > 0 && (
        <div className="entity-fact-reveal-chips">
          {chips.map((c, i) => (
            <span key={i} className="entity-fact-reveal-chip">{c}</span>
          ))}
        </div>
      )}
    </div>
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

// Module-level promise cache so repeated clicks on different classes
// inside the same modal session don't refetch the ontology document.
const _classDocCache: Map<string, Promise<any[]>> = new Map();
function fetchClassesCached(ontologyId: string): Promise<any[]> {
  let p = _classDocCache.get(ontologyId);
  if (!p) {
    p = getOntologyClasses(ontologyId).catch(() => []);
    _classDocCache.set(ontologyId, p);
  }
  return p;
}

// Class-details panel — shown above the Facts section when a class
// node is selected in the evidence map. Renders the ontology class's
// description + attributes + relations from the ontology document
// (lazy-fetched, cached per ontology).
function ClassDetailsPanel({
  className,
  ontologyId,
  onDismiss,
}: {
  className: string;
  ontologyId: string | null;
  onDismiss?: () => void;
}) {
  const [klass, setKlass] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!ontologyId) {
      setKlass(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchClassesCached(ontologyId)
      .then((classes) => {
        if (cancelled) return;
        const match = (classes || []).find((c: any) => c.name === className) || null;
        setKlass(match);
      })
      .catch(() => { if (!cancelled) setKlass(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [ontologyId, className]);

  return (
    <div className="graph-modal-side-legend-section class-details-section">
      <div className="graph-modal-side-legend-section-label selection-label">
        <span>Class · {className}</span>
        {onDismiss && (
          <button
            type="button"
            className="graph-modal-side-legend-dismiss"
            onClick={onDismiss}
            aria-label="Clear selection"
          >×</button>
        )}
      </div>
      {!ontologyId && (
        <div className="class-details-empty">
          This class isn't backed by a registered ontology (often the
          case for hand-authored intake facts like Policy / ActorScope).
        </div>
      )}
      {ontologyId && loading && !klass && (
        <div className="class-details-empty">Loading class definition…</div>
      )}
      {ontologyId && !loading && !klass && (
        <div className="class-details-empty">
          The {className} class isn't defined in the {ontologyId} ontology
          document — likely a freshly-added scenario class.
        </div>
      )}
      {klass && (
        <>
          {(klass.plain_description || klass.description) && (
            <p className="class-details-desc">
              {klass.plain_description || klass.description}
            </p>
          )}
          {Array.isArray(klass.attributes) && klass.attributes.length > 0 && (
            <div className="class-details-block">
              <div className="class-details-sublabel">Attributes</div>
              <ul className="class-details-attrs">
                {klass.attributes.map((a: any, i: number) => (
                  <li key={i}>
                    <span className="class-details-attr-name">{a.name}</span>
                    <span className="class-details-attr-type">{a.type}</span>
                    {a.identifier && <span className="class-details-id-pill">id</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {Array.isArray(klass.relations) && klass.relations.length > 0 && (
            <div className="class-details-block">
              <div className="class-details-sublabel">Relations</div>
              <ul className="class-details-relations">
                {klass.relations.map((r: any, i: number) => (
                  <li key={i}>
                    {className} <strong>{r.name}</strong>{" "}
                    {r.cardinality === "0..*" || r.cardinality === "1..*" ? "many" : "a"}{" "}
                    <strong>{r.target}</strong>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <button
            type="button"
            className="class-details-more"
            onClick={() =>
              window.dispatchEvent(
                new CustomEvent("open-case-spec", {
                  detail: { tab: "ontology", anchor: `spec-class-${className}` },
                }),
              )
            }
          >Open full spec ⤢</button>
        </>
      )}
    </div>
  );
}

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

    // Platform-flow Scenario node → pop the Case-spec modal on the
    // Scenario tab. Single-click suffices because nothing else competes
    // for this node.
    if (id === "pf:scenario") {
      window.dispatchEvent(
        new CustomEvent("open-case-spec", { detail: { tab: "scenario" } }),
      );
      return;
    }

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
    const nodeClasses = node.classes();

    // Knowledge-graph node — surface its ontology class definition.
    // No fact list (Neo4j subgraph nodes don't carry case-level facts),
    // but the ClassDetailsPanel in the legend still renders the class
    // description + attributes + relations from /api/ontologies/.../classes.
    // Hardcoded "supply_chain" because that's the only ontology the
    // knowledge-graph subgraph is mapped to in this demo.
    if (nodeClasses.includes("graph-node")) {
      const nodeType = String(node.data("nodeType") || node.data("label") || "");
      if (nodeType) {
        setFacts({ className: nodeType, ontologyId: "supply_chain", facts: [] });
      } else {
        setFacts(null);
      }
      return;
    }

    if (!nodeClasses.includes("evidence-class")) {
      setFacts(null);
      return;
    }
    const className = String(node.data("ontology_class") || node.data("label") || id).split("\n")[0];
    const ontologyId = (node.data("ontology_id") as string | undefined) || null;
    const facts = (node.data("facts") || []) as Array<{
      id: string;
      title: string;
      source: string;
      source_kind: string;
    }>;
    setFacts({ className, ontologyId, facts });
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

// Click-to-reveal: when an entity node is tapped, look up the node id in the
// case's facts (across every stage) and surface the matching fact to the
// side legend. Background-tapping clears the reveal. Idempotent via scratch
// flag — react-cytoscape re-invokes the cy callback on every re-render. The
// `active` snapshot is captured at attach time, which is fine because the
// modal closes (and the cy instance disposes) whenever active changes.
function attachEntityFactClickReveal(
  cy: cytoscape.Core,
  active: CaseFull | null,
  setReveal: (r: EntityFactReveal | null) => void,
) {
  if (cy.scratch("_kfEntityFactReveal")) return;
  cy.scratch("_kfEntityFactReveal", true);
  cy.on("tap", "node", (evt: any) => {
    const nodeId = evt.target.id();
    if (!active?.stages) {
      setReveal(null);
      return;
    }
    for (const stage of active.stages) {
      for (const fact of stage.facts ?? []) {
        if (fact.id === nodeId) {
          setReveal({ fact, stageName: stage.stage });
          return;
        }
      }
    }
    // Node has no matching fact card — clear any prior reveal so the side
    // panel doesn't show a stale card. Common for graph-context nodes that
    // the case didn't bind (e.g. a holding company surfaced by the walk but
    // not returned by any of the scenario's queries).
    setReveal(null);
  });
  cy.on("tap", (evt: any) => {
    if (evt.target === cy) setReveal(null);
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
      // rankDir: LR (left-to-right) reads naturally for directed supply-chain
      // walks (supplier → PO → product → program). Bumped nodeSep + rankSep
      // so 15-node subgraphs (Aeronova) don't overlap labels. Padding
      // ensures fit() leaves room around the whole tree.
      return {
        name: "dagre",
        rankDir: "LR",
        nodeSep: 45,
        rankSep: 110,
        edgeSep: 18,
        padding: 30,
        animate: false,
      };
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
  // source kinds it was bound through, the actual facts, and (when
  // tagged by the OntologyResolver) the ontology id this class came
  // from — so the side legend can lazy-fetch its definition.
  const stagesByClass = new Map<string, Set<string>>();
  const sourcesByClass = new Map<string, Set<string>>();
  const factsByClass = new Map<string, FactFlat[]>();
  const ontologyByClass = new Map<string, string>();
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
      // OntologyResolver tags resolved facts with `via_ontology` so we
      // know which ontology to fetch the class definition from. Static
      // / hand-authored facts (intake stage) won't have it — that's OK,
      // those classes (Policy, ActorScope) tend to be self-explanatory.
      // The backend formats this as "ontology_id.ClassName" (a
      // fully-qualified tag); strip the class suffix so the legend hits
      // the right /api/ontologies/<id>/classes endpoint.
      if (f.via_ontology && !ontologyByClass.has(cls)) {
        const ontId = f.via_ontology.includes(".")
          ? f.via_ontology.split(".")[0]
          : f.via_ontology;
        ontologyByClass.set(cls, ontId);
      }
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
    const ontologyId = ontologyByClass.get(cls) || "";
    elements.push({
      data: {
        id: classId,
        label: `${cls}\n(${facts.length} fact${facts.length === 1 ? "" : "s"})`,
        facts,
        ontology_id: ontologyId,
        ontology_class: cls,
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
  const PLATFORM_FLOW_EXPLAINER =
    "How this case was answered, end to end. Your query matched a " +
    "scenario (the recipe), which asked specific ontology classes for " +
    "facts, which were resolved through these data sources, leading to " +
    "the outcome. Click the Scenario node to see its full recipe; click " +
    "any class to see what it represents.";
  if (!active) {
    return (
      <GraphModal
        title="Platform flow"
        subtitle="Open a case to see how the platform answered the query."
        explainer={PLATFORM_FLOW_EXPLAINER}
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
        explainer={PLATFORM_FLOW_EXPLAINER}
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
          explainer={
            "The corporate ownership + supplier network around the case " +
            "subject, pulled live from Neo4j. Click any node to see what " +
            "ontology class it represents."
          }
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
  // Hidden-dependency path highlight — applied by hidden-dep effect when an
  // AlternativeSupplier fact carries via_node_id. Both endpoint nodes
  // (failing supplier + proposed alternate) AND the intermediate holding
  // node get the amber treatment; the connecting edges get matching colour
  // so the 2-hop chain visually pops without dimming the rest of the graph
  // (the user can still click-explore freely).
  {
    selector: "node.cy-hidden-dep-path",
    style: {
      "border-width": 3,
      "border-color": "#b46d00",
      "border-style": "solid",
      "background-color": "#fff4dc",
      "z-index": 100,
    },
  },
  {
    selector: "edge.cy-hidden-dep-path",
    style: {
      "line-color": "#b46d00",
      "target-arrow-color": "#b46d00",
      "source-arrow-color": "#b46d00",
      width: 3,
      "opacity": 1,
      "z-index": 99,
    },
  },
  // Decision-pathways tab — two-colour semantic palette.
  //   • cy-impact-path    → RED (at-risk: programs / SKUs / buyers)
  //   • cy-proposed-path  → GREEN (swap candidates)
  //   • cy-pathway-terminal → emphasised border on the destination node
  //                            (the numbered "1 ·", "2 ·" label is set by
  //                            the React effect via data("label"))
  //   • cy-pathway-dim    → 12% opacity on everything off all pathways
  // Order matters: cy-proposed-path sits AFTER cy-hidden-dep-path so that
  // when both apply (Pathways tab) the green wins. On the Network tab
  // only cy-hidden-dep-path is applied, so the chain reads amber there.
  {
    selector: "node.cy-impact-path",
    style: {
      "border-width": 2,
      "border-style": "solid",
      "border-color": "#c14a4a",
      "background-color": "#fee2e2",
      "z-index": 60,
    },
  },
  {
    selector: "edge.cy-impact-path",
    style: {
      width: 2,
      "line-color": "#c14a4a",
      "target-arrow-color": "#c14a4a",
      "opacity": 1,
      "z-index": 59,
    },
  },
  {
    selector: "node.cy-proposed-path",
    style: {
      "border-width": 2,
      "border-style": "solid",
      "border-color": "#16a34a",
      "background-color": "#dcfce7",
      "z-index": 60,
    },
  },
  {
    selector: "edge.cy-proposed-path",
    style: {
      width: 2,
      "line-color": "#16a34a",
      "target-arrow-color": "#16a34a",
      "opacity": 1,
      "z-index": 59,
    },
  },
  // Context-path (at-risk programs) — slate, distinct from the
  // green-recommended and red-avoid chains because these aren't
  // supplier choices, they're the business stake the decision is
  // protecting. Rendered with the same step-numbered terminal labels
  // ("5 · Mirage Avionics platform" / "$48M · $220k/day") so the
  // reviewer can see what's at risk without leaving the graph.
  {
    selector: "node.cy-context-path",
    style: {
      "border-width": 2,
      "border-style": "solid",
      "border-color": "#64748b",
      "background-color": "#e2e8f0",
      "z-index": 55,
    },
  },
  {
    selector: "edge.cy-context-path",
    style: {
      width: 1.6,
      "line-color": "#64748b",
      "target-arrow-color": "#64748b",
      "opacity": 1,
      "z-index": 54,
    },
  },
  {
    selector: "edge.cy-context-path.cy-pathway-edge-reverse",
    style: { "source-arrow-color": "#64748b" },
  },
  // Failing node — the START of every pathway. Black so it's
  // immediately recognisable as the origin of every chain. The "1 · …"
  // label prefix set in the React effect makes "step 1" explicit too.
  {
    selector: "node.cy-pathway-failing",
    style: {
      "border-width": 3,
      "border-color": "#000000",
      "border-style": "solid",
      "background-color": "#000000",
      "font-weight": 700,
      "z-index": 65,
    },
  },
  // Terminal nodes — thicker border + bolder label. text-max-width is
  // bumped from the base 110px to 180px so the second-line WHY suffix
  // ("$48M · $220k/day" / "⚠ qual lapsed 2026-04-15 · shared parent")
  // fits without auto-wrapping mid-phrase.
  {
    selector: "node.cy-pathway-terminal",
    style: {
      "border-width": 3,
      "font-weight": 700,
      "font-size": 11,
      "text-max-width": 180,
    },
  },
  // Pathway view = decision graph, not cypher graph. Edges flagged
  // cy-pathway-edge-reverse render their arrow at the SOURCE end (so the
  // visible flow points to the higher-step node) instead of the target.
  // Source-arrow colour mirrors the path colour so it stays visually
  // consistent with the rest of the chain.
  {
    selector: "edge.cy-pathway-edge-reverse",
    style: {
      "target-arrow-shape": "none",
      "source-arrow-shape": "triangle",
    },
  },
  {
    selector: "edge.cy-impact-path.cy-pathway-edge-reverse",
    style: { "source-arrow-color": "#c14a4a" },
  },
  {
    selector: "edge.cy-proposed-path.cy-pathway-edge-reverse",
    style: { "source-arrow-color": "#16a34a" },
  },
  // Off-pathway elements: hidden on Pathways tab so the canvas shows ONLY
  // the decision chains. Display:none keeps their layout positions intact
  // (no expensive re-layout on tab flip) but removes them from the view.
  { selector: ".cy-pathway-dim", style: { display: "none" } },
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

  // Per-ontology-type colours — match the side-legend swatches in
  // styles.css (.dot-type-Supplier, .dot-type-PurchaseOrder, etc.).
  // Listed AFTER accent-default so a "default" node still picks up its
  // type colour; the special-purpose accents (anchor / risk / risk_path /
  // alt) are listed BEFORE so they win for the failing supplier, the
  // sanctioned entities, the carrier-alliance reach, etc. Hidden-dep +
  // pathway classes win last (they're added/removed dynamically).
  {
    selector: "node.type-Supplier",
    style: { "background-color": "#c45a3e", "border-color": "#8a3f29", color: "#5a2818" },
  },
  {
    selector: "node.type-Carrier",
    style: { "background-color": "#c45a3e", "border-color": "#8a3f29", color: "#5a2818" },
  },
  {
    selector: "node.type-SanctionedNetworkEntity",
    style: { "background-color": "#d24545", "border-color": "#7a2424", color: "#5a1818" },
  },
  {
    selector: "node.type-HoldingCompany",
    style: { "background-color": "#5a6678", "border-color": "#2f3845", color: "#1f2937" },
  },
  {
    selector: "node.type-Alliance",
    style: { "background-color": "#a08550", "border-color": "#5e4924", color: "#5e4924" },
  },
  {
    selector: "node.type-PurchaseOrder",
    style: { "background-color": "#3a8a8a", "border-color": "#266060", color: "#1a3838" },
  },
  {
    selector: "node.type-Product",
    style: { "background-color": "#9b6db0", "border-color": "#5e4070", color: "#3d2950" },
  },
  {
    selector: "node.type-Program",
    style: { "background-color": "#d4a93a", "border-color": "#8a6d20", color: "#5a4514" },
  },

  // Special accents — listed AFTER per-type so the failing supplier
  // (anchor), sanctioned entities (risk), risk-path neighbours, and
  // carrier-alliance reach (alt) still pop above the type colour.
  // Re-declared in source order so cytoscape's later-wins cascade keeps
  // these on top of the per-type rules above.
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
  {
    selector: "node.accent-risk_path",
    style: {
      "background-color": "#94a3b8",
      "border-color": "#c14a4a",
      "border-width": 1.5,
      color: "#7a2424",
    },
  },
  {
    selector: "node.accent-alt",
    style: {
      "background-color": "#a16207",
      "border-color": "#854d0e",
      color: "#854d0e",
    },
  },

  // Edges — hairlines with directed-graph arrows so the cypher direction is
  // legible at a glance (e.g. SOURCES_FROM points to the upstream supplier;
  // PLACED points from supplier to PO). The arrow matches the line colour
  // and rides at the target end. Label sits over a cream pill matching the
  // canvas so the edge line doesn't visually slice through the relationship
  // text. text-background-shape: roundrectangle keeps the pill compact.
  {
    selector: "edge.graph-edge",
    style: {
      width: 0.6,
      "line-color": "rgba(15,23,42,0.55)",
      "target-arrow-shape": "triangle",
      "target-arrow-color": "rgba(15,23,42,0.55)",
      "arrow-scale": 0.9,
      "curve-style": "bezier",
      label: "data(label)",
      "font-family": "DM Mono, ui-monospace, monospace",
      "font-size": 9,
      "text-rotation": "autorotate",
      color: "rgba(15,23,42,0.85)",
      "text-background-color": "#faf7f0",
      "text-background-opacity": 1,
      "text-background-padding": "2px",
      "text-background-shape": "roundrectangle",
    },
  },
  {
    selector: "edge.edge-accent-risk_path",
    style: {
      "line-color": "#c14a4a",
      "target-arrow-color": "#c14a4a",
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
