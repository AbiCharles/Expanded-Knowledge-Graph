import { useEffect, useMemo, useState } from "react";
import { CaseFull, DecisionKind, MatchedPromotedPattern, StagePayload } from "../types";
import { ActionLifecycleCard } from "./ActionLifecycleCard";
import { CounterfactualCard } from "./CounterfactualCard";
import { EvidenceMap, GraphPanel } from "./GraphViz";

// Plain-English labels for the operator. Raw stage names (agent_intake /
// proposal / review) survive in the tooltip via title= for engineers.
const STAGE_LABEL: Record<string, string> = {
  agent_intake: "Policy & scope",
  proposal: "Agent gathered",
  review: "For your decision",
};

export function Envelope({
  active,
  onRefresh,
  onReplay,
  onBaselineReplay,
  onCompare,
  baselineRunningForActive,
  externalOpenNetworkSignal,
  externalOpenPathwaysSignal,
  aeronovaFindings,
  graphFocusIds,
}: {
  active: CaseFull | null;
  onRefresh?: () => void;
  onReplay?: (caseId: string, decision: DecisionKind) => void;
  onBaselineReplay?: (caseId: string) => void;
  onCompare?: (caseId: string) => void;
  baselineRunningForActive?: boolean;
  // W8 deep-link signals. App.tsx bumps these counters when a
  // ?launch=aeronova&view=… URL needs to open the knowledge graph
  // at a specific tab. Combined with the existing Envelope-internal
  // openPathwaysSignal so the same GraphPanel signal contract works
  // for both internal triggers (CounterfactualCard OK button) and
  // external triggers (agent-orchestrator deep-link).
  externalOpenNetworkSignal?: number;
  externalOpenPathwaysSignal?: number;
  aeronovaFindings?: import("../api").AeronovaFindings | null;
  graphFocusIds?: string[];
}) {
  // W1 / Beat 3 — revision selector. Default to viewing the LATEST
  // revision so users see the freshest decision; users can toggle back
  // to v1 to see the original. When the case has no revisions (still
  // in progress), fall back to `active.stages` like before.
  const revisions = active?.revisions ?? [];
  const latestRevisionNo =
    revisions.length > 0
      ? revisions[revisions.length - 1].revision_no
      : (active?.current_revision ?? 1);
  const [selectedRevisionNo, setSelectedRevisionNo] = useState<number | null>(null);
  // Reset to "latest" whenever the case changes or a new revision lands.
  useEffect(() => {
    setSelectedRevisionNo(null);
  }, [active?.case_id, revisions.length]);
  // Counter signal that, when bumped, makes GraphPanel auto-open its
  // modal pre-selected to the Decision-pathways tab. Bumped by the OK
  // button in the post-revision modal that CounterfactualCard raises.
  const [openPathwaysSignal, setOpenPathwaysSignal] = useState(0);
  const effectiveRevisionNo = selectedRevisionNo ?? latestRevisionNo;
  const selectedRevision =
    revisions.find((r) => r.revision_no === effectiveRevisionNo) ?? null;

  // Compute which fact ids are NEW in the selected revision (relative to
  // the prior revision) so the FactCard can render a green gutter.
  const newFactKeys = useMemo(() => {
    if (!selectedRevision) return new Set<string>();
    const idx = revisions.findIndex(
      (r) => r.revision_no === selectedRevision.revision_no,
    );
    if (idx <= 0) return new Set<string>();
    const prior = revisions[idx - 1];
    const priorKeys = new Set(
      (prior.stages_snapshot ?? []).flatMap((s) =>
        s.facts.map((f) => `${f.source}|${f.ontology_type}|${f.id}`),
      ),
    );
    const out = new Set<string>();
    for (const stage of selectedRevision.stages_snapshot ?? []) {
      for (const f of stage.facts) {
        const k = `${f.source}|${f.ontology_type}|${f.id}`;
        if (!priorKeys.has(k)) out.add(k);
      }
    }
    return out;
  }, [revisions, selectedRevision]);

  // If a revision is selected, render its snapshot; otherwise the live
  // stages from the case (CaseFull.stages). Fall back to live stages
  // when the snapshot is empty (legacy cases where v1 was lazy-sealed
  // with ctx=None) so the Envelope + graph + evidence map don't all
  // disappear together.
  const snapshotStages = selectedRevision
    ? (selectedRevision.stages_snapshot as StagePayload[])
    : null;
  const stages =
    snapshotStages && snapshotStages.length > 0
      ? snapshotStages
      : (active?.stages ?? []);
  const factCount = stages.reduce((acc, s) => acc + s.facts.length, 0);
  // Build an `effectiveActive` that mirrors `active` but with the
  // current revision's stages substituted in. Lets the GraphPanel,
  // EvidenceMap, and decision-pathway computations all "see" the new
  // evidence injected by /revise (Beat 3) instead of always reading
  // from the live state. Flipping the revision selector re-renders the
  // graph + pathways against the chosen revision's facts.
  //
  // Defensive fallbacks:
  //   - empty snapshot → keep live stages so cards don't vanish.
  //   - snapshot missing the failing-Supplier anchor → merge the live
  //     stages in front so the graph still has its anchor (the post-
  //     revision OK button must always land on a working graph; a null
  //     anchor would unmount GraphPanel and read as a blank Envelope).
  const effectiveActive = useMemo<CaseFull | null>(() => {
    if (!active) return null;
    if (!selectedRevision) return active;
    const snap = stages && stages.length > 0 ? stages : (active.stages ?? []);
    const hasFailingSupplier = snap.some((s) =>
      s.facts?.some(
        (f) =>
          f.ontology_type === "Supplier" &&
          typeof f.status === "string" &&
          f.status.startsWith("chapter_11"),
      ),
    );
    if (hasFailingSupplier) {
      return { ...active, stages: snap };
    }
    // Snapshot doesn't carry the anchor. Merge: take the live stages
    // (which DO have the anchor) and append any facts from the snapshot
    // that aren't already there, keyed by (source, ontology_type, id).
    // If live stages are ALSO empty (legacy reload with ctx=None), the
    // best we can do is keep the snapshot — at least the new fact shows.
    const liveStages = active.stages ?? [];
    if (liveStages.length === 0) {
      return { ...active, stages: snap };
    }
    const snapStagesByName = new Map(snap.map((s) => [s.stage, s]));
    const mergedStages: StagePayload[] = liveStages.map((live) => {
      const matching = snapStagesByName.get(live.stage);
      if (!matching) return live;
      const existingKeys = new Set(
        live.facts.map((f) => `${f.source}|${f.ontology_type}|${f.id}`),
      );
      const extras = matching.facts.filter(
        (f) => !existingKeys.has(`${f.source}|${f.ontology_type}|${f.id}`),
      );
      return extras.length > 0
        ? { ...live, facts: [...live.facts, ...extras] }
        : live;
    });
    return { ...active, stages: mergedStages };
  }, [active, selectedRevision, stages]);
  const [glossaryOpen, setGlossaryOpen] = useState(false);

  // Extract the executor's target cost (if any) so FreightRate cards can
  // self-highlight as CHOSEN when their total matches. Today only the
  // `new_total_cost_usd` arg is matched; widen this rule when new
  // numerically-keyed write actions land. Null means "no matching to do."
  const targetCostUsd: number | null = (() => {
    const args = active?.scenario?.executor?.arguments;
    if (!args) return null;
    const raw = args["new_total_cost_usd"];
    if (raw === null || raw === undefined) return null;
    const n = typeof raw === "number" ? raw : Number(raw);
    return Number.isFinite(n) ? n : null;
  })();

  return (
    <div className="envelope-wrapper">
      <div className="envelope-eyebrow">
        <div className="envelope-title">
          What the agent gathered
          <button
            type="button"
            className="glossary-trigger"
            onClick={() => setGlossaryOpen(true)}
            aria-label="Open glossary — what do the badges, source pills, and stage labels mean?"
            title="What do these labels mean?"
          >
            ?
          </button>
        </div>
        <div className="envelope-counter">
          <strong>{stages.length}</strong> stages · <strong>{factCount}</strong> facts
        </div>
      </div>
      {/* W1 / Beat 3 — revision selector. Renders v1 ▸ v2 pills when
          the case has 2+ revisions. Click switches the Envelope to that
          revision's snapshot. v2+ also gets a "new fact" green gutter on
          facts that didn't exist in the prior revision. */}
      {revisions.length > 1 && (
        <div className="revision-selector">
          <span className="revision-selector-label">Revisions</span>
          {revisions.map((r) => (
            <button
              key={r.revision_no}
              type="button"
              className={
                "revision-pill" +
                (r.revision_no === effectiveRevisionNo ? " active" : "")
              }
              onClick={() => setSelectedRevisionNo(r.revision_no)}
              title={`${r.trigger_label} · ${r.decision ?? "no decision"} · ${r.created_at}`}
            >
              v{r.revision_no}
              {r.decision && (
                <span className="revision-pill-decision">· {r.decision}</span>
              )}
            </button>
          ))}
          {selectedRevision && selectedRevision.revision_no > 1 && (
            <span className="revision-trigger-label">
              {selectedRevision.trigger_label}
            </span>
          )}
        </div>
      )}
      <div className="envelope">
        {/* W3 / Beat 4 — primary surface for the action lifecycle. Pinned
            at the top of the case so the Compensate CTA is visible without
            scrolling. Sticky position keeps it glued to the viewport top
            as the reviewer scrolls through Stages 1-4 below. Self-renders
            only when execution_result is set (most cases never fire an
            action, so the top of the Envelope reads normally). */}
        <ActionLifecycleCard active={active} onRefresh={onRefresh} />
        {/* W5 / Beat 2 — counterfactual exploration surface. Sits right
            below the Action Lifecycle card. Carries Run baseline +
            Replay-with-different-decision + Compare. Renders only on
            HITL-completed cases so most cases (and in-progress cases)
            see nothing here. */}
        {onReplay && onBaselineReplay && onCompare && (
          <CounterfactualCard
            active={active}
            onReplay={onReplay}
            onBaselineReplay={onBaselineReplay}
            onCompare={onCompare}
            baselineRunning={!!baselineRunningForActive}
            onRevised={onRefresh}
            onOpenPathways={() => setOpenPathwaysSignal((n) => n + 1)}
          />
        )}
        {stages.length === 0 && <div className="envelope-empty">Awaiting first binding…</div>}
        {active && (active.matched_promoted_patterns || []).length > 0 && (
          <PromotedPatternBanner patterns={active.matched_promoted_patterns!} />
        )}
        {effectiveActive && stages.length > 0 && (
          <>
            <EvidenceMap active={effectiveActive} />
            <GraphPanel
              active={effectiveActive}
              openPathwaysSignal={
                (openPathwaysSignal || 0) +
                (externalOpenPathwaysSignal || 0)
              }
              openNetworkSignal={externalOpenNetworkSignal}
              aeronovaFindings={aeronovaFindings}
              focusIds={graphFocusIds}
            />
          </>
        )}
        {selectedRevision && selectedRevision.revision_no > 1 && newFactKeys.size > 0 && (
          <div className="revision-evidence-banner">
            <div className="revision-evidence-banner-eyebrow">
              ⚡ Showing v{selectedRevision.revision_no} — re-versioned by new evidence
            </div>
            <div className="revision-evidence-banner-body">
              <strong>{selectedRevision.trigger_label}</strong>
              {" "}surfaced {newFactKeys.size} new fact{newFactKeys.size === 1 ? "" : "s"}.
              Look for the <span className="revision-evidence-banner-chip">NEW EVIDENCE</span> strip
              in the stage cards below. The knowledge graph and decision pathways have re-rendered
              to reflect this revision; switch to v1 to see the original state.
            </div>
          </div>
        )}
        {stages.map((s, idx) => (
          <StageBlock
            key={s.stage}
            stage={s}
            index={idx}
            targetCostUsd={targetCostUsd}
            newFactKeys={newFactKeys}
          />
        ))}
      </div>
      {glossaryOpen && <GlossaryModal onClose={() => setGlossaryOpen(false)} />}
    </div>
  );
}

function StageBlock({
  stage,
  index,
  targetCostUsd,
  newFactKeys,
}: {
  stage: StagePayload;
  index: number;
  targetCostUsd: number | null;
  newFactKeys?: Set<string>;
}) {
  // Each stage starts expanded (the user wants to see the work). Click the
  // header to collapse. Inside, the facts grid is capped with internal scroll
  // so a 30-fact port-disruption stage doesn't push the page below the fold.
  const [open, setOpen] = useState(true);
  // QueryPlanPanel can ask to highlight cards from one query. null = no
  // filter applied; matching facts get .fact-highlighted, the rest get
  // .fact-dimmed.
  const [highlightedQuery, setHighlightedQuery] = useState<number | null>(null);
  const hasQueries = !!stage.queries && stage.queries.length > 0;
  return (
    <div className={`stage-block${open ? " stage-open" : " stage-collapsed"}`}>
      <button
        type="button"
        className="stage-header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={`Raw stage id: ${stage.stage} · binder ${stage.binder}`}
      >
        <div className="stage-name">
          <span className="stage-chevron" aria-hidden="true">▸</span>
          Stage {index + 1} · {STAGE_LABEL[stage.stage] ?? stage.stage}
          <span className="stage-fact-count">({stage.facts.length})</span>
        </div>
        <div className="stage-binder">{stage.binder}</div>
      </button>
      {open && hasQueries && (
        <QueryPlanPanel
          queries={stage.queries!}
          highlighted={highlightedQuery}
          onHighlight={setHighlightedQuery}
        />
      )}
      {open && (
        <FactsGrid
          facts={stage.facts}
          highlightedQuery={highlightedQuery}
          targetCostUsd={targetCostUsd}
          newFactKeys={newFactKeys}
        />
      )}
    </div>
  );
}

// "Why these cards?" — surfaces the ontology_queries the binder ran, in order,
// with their declared purpose + how many cards each returned. Click a row
// to highlight the matching cards below (and dim the rest). Click again to
// clear. Collapsed by default to stay out of the way.
function QueryPlanPanel({
  queries,
  highlighted,
  onHighlight,
}: {
  queries: StagePayload["queries"];
  highlighted: number | null;
  onHighlight: (idx: number | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const qs = queries || [];
  return (
    <details
      className={`query-plan${open ? " query-plan-open" : ""}`}
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
    >
      <summary className="query-plan-summary">
        <span className="query-plan-eyebrow">
          Why these cards?
          <span className="query-plan-count">
            {" "}({qs.length} {qs.length === 1 ? "query" : "queries"} ran)
          </span>
        </span>
        <span className="query-plan-chevron" aria-hidden="true">▸</span>
      </summary>
      <ol className="query-plan-list">
        {qs.map((q) => {
          const isActive = highlighted === q.index;
          const whereStr = Object.entries(q.where)
            .filter(([k]) => !k.startsWith("__"))
            .map(([k, v]) => `${k}=${formatWhereVal(v)}`)
            .join(", ");
          return (
            <li
              key={q.index}
              className={`query-plan-item${isActive ? " active" : ""}`}
            >
              <button
                type="button"
                className="query-plan-item-btn"
                onClick={() => onHighlight(isActive ? null : q.index)}
              >
                <span className="query-plan-item-purpose">
                  {q.purpose || `${q.ontology}.${q.ontology_type}`}
                </span>
                <span className="query-plan-item-meta">
                  {q.fact_count} {q.fact_count === 1 ? "card" : "cards"}
                  {whereStr ? ` · where ${whereStr}` : " · no filter"}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {highlighted !== null && (
        <button
          type="button"
          className="query-plan-clear"
          onClick={() => onHighlight(null)}
        >
          Clear highlight
        </button>
      )}
    </details>
  );
}

function formatWhereVal(v: unknown): string {
  if (v === null || v === undefined) return "(any)";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try { return JSON.stringify(v); } catch { return String(v); }
}

// Cap large stages (e.g. port-disruption returns 30 shipments) at 12 visible
// facts with a "+ N more" expander. Keeps scroll cost predictable.
const FACT_PREVIEW_LIMIT = 12;

function FactsGrid({
  facts,
  highlightedQuery,
  targetCostUsd,
  newFactKeys,
}: {
  facts: StagePayload["facts"];
  highlightedQuery: number | null;
  targetCostUsd: number | null;
  newFactKeys?: Set<string>;
}) {
  const [showAll, setShowAll] = useState(false);
  const overflow = facts.length > FACT_PREVIEW_LIMIT;
  const visible = showAll || !overflow ? facts : facts.slice(0, FACT_PREVIEW_LIMIT);
  return (
    <>
      <div className="facts-grid">
        {visible.map((f, i) => {
          const highlightState: "highlighted" | "dimmed" | "" =
            highlightedQuery === null
              ? ""
              : f.query_index === highlightedQuery
              ? "highlighted"
              : "dimmed";
          const factKey = `${f.source}|${f.ontology_type}|${f.id}`;
          const isNewInRevision = !!newFactKeys?.has(factKey);
          return (
            <FactCard
              key={`${f.source}-${f.id}-${i}`}
              fact={f}
              index={i}
              highlightState={highlightState}
              targetCostUsd={targetCostUsd}
              isNewInRevision={isNewInRevision}
            />
          );
        })}
      </div>
      {overflow && (
        <button
          type="button"
          className="facts-show-more"
          onClick={() => setShowAll((v) => !v)}
        >
          {showAll
            ? `Show fewer (collapse to ${FACT_PREVIEW_LIMIT})`
            : `Show all ${facts.length} (${facts.length - FACT_PREVIEW_LIMIT} more)`}
        </button>
      )}
    </>
  );
}

// Marker words that signal a fact needs visual emphasis. Matched
// case-insensitively against title + summary. Keep this small — every keyword
// adds noise to facts that happen to mention the word.
const HIGH_RISK_MARKERS = ["delayed", "customs_hold", "damage", "vessel_change", "exception", "critical"];
const HIGH_CONGESTION_MARKERS = ["congestion HIGH", "HIGH (berth", "labor action true", "weather true"];
const PREMIUM_MARKERS = ["SLA premium", "premium ·"];

function factAccent(text: string): "" | "risk" | "warning" | "premium" {
  const t = text || "";
  if (HIGH_RISK_MARKERS.some((m) => t.toLowerCase().includes(m))) return "risk";
  if (HIGH_CONGESTION_MARKERS.some((m) => t.includes(m))) return "warning";
  if (PREMIUM_MARKERS.some((m) => t.includes(m))) return "premium";
  return "";
}

// Decide whether a fact card should be styled as the CHOSEN rate (the one
// the action will commit) vs an ALTERNATIVE (shown for comparison). Only
// applies to FreightRate cards when a target cost is supplied. Falls back
// to "" (no styling) for any other class or when no executor target exists.
function computeChosenState(
  fact: { ontology_type: string; summary: string | null },
  targetCostUsd: number | null,
): "chosen" | "alternative" | "" {
  if (fact.ontology_type !== "FreightRate") return "";
  if (targetCostUsd === null) return "";
  // FreightRate summary format includes "$<total>" as the first dollar
  // amount. Grab it, strip commas/cents, and numerically compare.
  const m = (fact.summary || "").match(/\$([\d,]+(?:\.\d+)?)/);
  if (!m) return "alternative";
  const cost = Number(m[1].replace(/,/g, ""));
  if (!Number.isFinite(cost)) return "alternative";
  return Math.abs(cost - targetCostUsd) < 1 ? "chosen" : "alternative";
}

// Plain-English presentation for each ontology class that can land on a fact
// card. Keeps the technical class name available in the API/audit trail but
// shows a non-engineer-friendly label + one-line "what is this?" subtitle
// inside the card. Add new entries here when new ontology classes appear.
const CLASS_DISPLAY: Record<string, { label: string; description: string }> = {
  // Logistics ontology
  Shipment: {
    label: "Shipment",
    description: "An in-flight or recently completed shipment — origin, destination, vessel, current position, ETA, port state.",
  },
  ShipmentEvent: {
    label: "Milestone event",
    description: "One step on the shipment's journey (booked → picked up → port arrival → customs → delivered, plus any exceptions).",
  },
  ShipmentPerformance: {
    label: "Performance summary",
    description: "Aggregated on-time rate and late count for a SKU over a reporting period.",
  },
  Carrier: {
    label: "Carrier scorecard",
    description: "Carrier master record — SCAC, mode, on-time and damage rates, contract renewal date.",
  },
  Lane: {
    label: "Lane",
    description: "An origin-destination corridor with target vs. actual transit performance and current congestion.",
  },
  Port: {
    label: "Port",
    description: "Port operational state — congestion level, berth wait time, customs clearance speed, disruption flags.",
  },
  CustomerOrder: {
    label: "Customer order",
    description: "Customer order tied to a shipment — SLA tier, promised delivery date, $/day late penalty.",
  },
  Booking: {
    label: "Carrier booking",
    description: "The active carrier booking that physically moves the shipment. Write target for re-tender actions.",
  },
  BookingHistory: {
    label: "Recent booking change",
    description: "An entry in the booking change log — captures the prior carrier/cost/status and the case that triggered the change. Surfaced on replay so the reviewer sees how the current state got there.",
  },
  FreightRate: {
    label: "Rate option",
    description: "A current contract or spot rate card per lane × carrier × container type — compared against the current booking when re-tendering.",
  },
  DemurrageCharge: {
    label: "Demurrage charge",
    description: "Accessorial fee for exceeding free time at a port or yard. Carries status (accruing → billed → disputed → waived/paid) and prior dispute history.",
  },
  // supply_chain — graph-resident classes (Neo4j)
  SanctionsProximity: {
    label: "Sanctions-proximity trail",
    description: "A shortest-path traversal from the supplier through its corporate network to a sanctioned entity within 4 hops. The trail shows every node on the path — this is what flat tables can't answer.",
  },
  AlliancePeer: {
    label: "Alliance-peer carrier",
    description: "Another carrier in the same shipping alliance as one the supplier prefers. Surfaces concentration risk: 'multiple carriers, one alliance, single point of failure.'",
  },
  // tcs_core (used by logistics scenarios for cross-domain context)
  Product: {
    label: "Product",
    description: "Sales item / SKU master record — ECCN, HTS, category.",
  },
  SanctionedEntity: {
    label: "Sanctioned entity",
    description: "Counterparty on a sanctions list (OFAC SDN-style).",
  },
  PriorOverride: {
    label: "Prior similar case",
    description: "How a previous reviewer decided a similar case — outcome + rationale. Shown so reviewers can calibrate against precedent.",
  },
  PolicyExcerpt: {
    label: "Policy excerpt",
    description: "Relevant SOP / policy paragraph pulled from the policy corpus via semantic search.",
  },
  // Inline facts (not ontology-resolved) authored directly in scenarios
  Policy: {
    label: "Active rule",
    description: "The policy that governs whether this action is permitted.",
  },
  ActorScope: {
    label: "Agent permissions",
    description: "The named capabilities the agent has — what it can read, propose, or write under this scenario.",
  },
};

function classDisplay(ontologyType: string): { label: string; description: string } {
  return CLASS_DISPLAY[ontologyType] || {
    label: ontologyType,
    description: "",
  };
}

function FactCard({
  fact,
  index,
  highlightState = "",
  targetCostUsd = null,
  isNewInRevision = false,
}: {
  fact: StagePayload["facts"][number];
  index: number;
  highlightState?: "highlighted" | "dimmed" | "";
  targetCostUsd?: number | null;
  isNewInRevision?: boolean;
}) {
  const accent = factAccent(`${fact.title} ${fact.summary}`);
  const cls = classDisplay(fact.ontology_type);
  // Detect whether this card is the FreightRate row whose total matches
  // the executor's target cost — the "chosen" rate the action will commit.
  // Falls back gracefully when the card isn't a FreightRate, no target was
  // set, or the summary string doesn't parse cleanly.
  const chosenState = computeChosenState(fact, targetCostUsd);
  // Hidden-dependency callout: fires when a graph resolver tagged this fact
  // with tier >= 2 (upstream supply chain) OR hops >= 2 (indirect relationship
  // path). Both are signals the entity is NOT reached by a direct contract /
  // PO / ownership edge — the kind of risk that a flat-table query would miss.
  // The deck's "hidden tier-2 dependency surfaced before any decision" beat
  // lands here.
  const tierDepth = typeof fact.tier === "number" ? fact.tier : null;
  const hopDepth = typeof fact.hops === "number" ? fact.hops : null;
  const isHiddenDep =
    (tierDepth !== null && tierDepth >= 2) ||
    (hopDepth !== null && hopDepth >= 2);
  // Role pill — surfaces a card's role in the current scenario at a glance
  // so the reviewer doesn't have to read the title to know "is this the
  // failing supplier or a proposed swap candidate?". Keyed off ontology_type
  // (plus the structured `status` field for the failing-Supplier case).
  const rolePill: { label: string; variant: string; title: string } | null = (() => {
    if (
      fact.ontology_type === "Supplier" &&
      typeof fact.status === "string" &&
      fact.status.startsWith("chapter_11")
    ) {
      return {
        label: "FAILING",
        variant: "failing",
        title:
          "FAILING — this supplier filed for bankruptcy protection. " +
          "The case exists in response to this event; everything " +
          "downstream is mitigation.",
      };
    }
    if (fact.ontology_type === "AlternativeSupplier") {
      return {
        label: "PROPOSED ALT",
        variant: "proposed-alt",
        title:
          "PROPOSED ALTERNATIVE — a swap candidate surfaced by the graph " +
          "walk. Not yet vetted; the reviewer must check the qualification " +
          "state and the relationship vector before approving any swap.",
      };
    }
    if (fact.ontology_type === "DownstreamDependent") {
      return {
        label: "AFFECTED BUYER",
        variant: "affected-buyer",
        title:
          "AFFECTED BUYER — a downstream supplier that depends on the " +
          "failing tier-N node via SOURCES_FROM edges. Its programs feel " +
          "the pain if the failing supplier stops shipping.",
      };
    }
    if (fact.ontology_type === "ProgramImpact") {
      return {
        label: "AT-RISK PROGRAM",
        variant: "at-risk-program",
        title:
          "AT-RISK PROGRAM — a customer program whose SKUs depend on the " +
          "failing supplier. Revenue + OTD-penalty figures show the stake.",
      };
    }
    return null;
  })();
  // Humanise the via_path label for the hidden-dependency callout — strips
  // the prefix ("sibling via Northgate Industrial Holdings (HoldingCompany)"
  // -> "Northgate Industrial Holdings") so the reader sees the entity name
  // rather than the cypher-friendly label.
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
  // Split the pipe-delimited summary into individual chips. Each segment
  // gets a small badge so the eye lands on the data, not a long sentence.
  const chips = (fact.summary || "")
    .split(/\s+·\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
  return (
    <div
      className={
        `fact${accent ? ` fact-accent-${accent}` : ""}` +
        (highlightState ? ` fact-${highlightState}` : "") +
        (chosenState ? ` fact-${chosenState}` : "") +
        (isNewInRevision ? " fact-new-in-revision" : "")
      }
      style={{ animationDelay: `${index * 80}ms` }}
    >
      {isNewInRevision && (
        <div
          className="fact-new-strip"
          title="New evidence — surfaced in this revision but not in the prior one."
        >
          ⚡ NEW EVIDENCE · ADDED IN THIS REVISION
        </div>
      )}
      <div className="fact-source">
        <SourcePill source={fact.source} />
        <span
          className="fact-ontology-type"
          title={`Ontology class: ${fact.ontology_type}`}
        >
          {cls.label}
        </span>
        {accent === "risk" && (
          <span
            className="fact-accent-badge risk"
            title="EXCEPTION — shipment flagged: delayed, customs hold, damage, vessel change, or port congestion. From the exception_flag column on the shipments table."
          >
            EXCEPTION
          </span>
        )}
        {accent === "warning" && (
          <span
            className="fact-accent-badge warning"
            title="CONGESTED — port-level friction: long berth wait, active labor action, or weather disruption. From the port master (ports.csv)."
          >
            CONGESTED
          </span>
        )}
        {accent === "premium" && (
          <span
            className="fact-accent-badge premium"
            title="PREMIUM SLA — customer order on the highest tier (typically large penalty per day late). From customer_orders.csv."
          >
            PREMIUM SLA
          </span>
        )}
        {chosenState === "chosen" && (
          <span
            className="fact-accent-badge chosen"
            title="CHOSEN — this is the rate the action will commit. The total here matches the executor's new_total_cost_usd argument."
          >
            CHOSEN
          </span>
        )}
        {chosenState === "alternative" && (
          <span
            className="fact-accent-badge alternative"
            title="ALTERNATIVE — surfaced for comparison; the scenario's chosen rate is a different card in this group."
          >
            ALT
          </span>
        )}
        {rolePill && (
          <span
            className={`fact-role-pill fact-role-${rolePill.variant}`}
            title={rolePill.title}
          >
            {rolePill.label}
          </span>
        )}
      </div>
      {isHiddenDep && (
        <div
          className={
            `fact-hidden-dep` +
            (tierDepth !== null ? ` fact-hidden-dep-tier` : ` fact-hidden-dep-hops`)
          }
          title={
            "Reached through multi-hop graph traversal — there is no direct " +
            "PO, contract, or ownership edge between you and this entity. " +
            "A flat-table query would not surface this risk."
          }
        >
          <span className="fact-hidden-dep-icon" aria-hidden="true">⚠</span>
          <span className="fact-hidden-dep-text">
            <strong>Hidden dependency</strong>
            {" · "}
            {tierDepth !== null && tierDepth >= 2 ? (
              <>
                tier-{tierDepth} supplier — reached by walking{" "}
                {tierDepth - 1} SOURCES_FROM edge
                {tierDepth - 1 > 1 ? "s" : ""} upstream
              </>
            ) : fact.via_path ? (
              <>
                {hopDepth}-hop chain via{" "}
                <strong>{humanizeViaPath(fact.via_path)}</strong> — no
                direct contract, PO, or ownership edge
              </>
            ) : (
              <>
                {hopDepth}-hop relationship chain — no direct contract path
              </>
            )}
          </span>
        </div>
      )}
      <div className="fact-id">{fact.title}</div>
      {cls.description && (
        <div className="fact-meaning">{cls.description}</div>
      )}
      <div className="fact-chips">
        {chips.map((c, i) => (
          <span className="fact-chip" key={i}>{c}</span>
        ))}
      </div>
      {fact.uri && (
        <a className="fact-uri" href="#" onClick={(e) => e.preventDefault()}>
          → {fact.uri}
        </a>
      )}
    </div>
  );
}

// Source strings come back as "csv:shipments_csv", "sqlite:logistics_sqlite",
// "kf:graph", etc. Render as a small colored pill: kind on the left, a
// human-friendly source label on the right (we strip the trailing "_csv"
// or "_sqlite" so it reads as a normal name).
function SourcePill({ source }: { source: string }) {
  const [kindRaw, nameRaw] = source.includes(":")
    ? source.split(":", 2)
    : ["source", source];
  const kind = kindRaw.toLowerCase();
  const name = (nameRaw || source)
    .replace(/_csv$/, "")
    .replace(/_sqlite$/, "")
    .replace(/_/g, " ");
  const description = kindDescription(kind);
  return (
    <span
      className={`source-pill source-pill-${kind}`}
      title={`${kindLabel(kind)} · ${description}\nRaw source id: ${source}`}
    >
      <span className="source-pill-kind">{kindLabel(kind)}</span>
      <span className="source-pill-name">{name}</span>
    </span>
  );
}

function kindLabel(kind: string): string {
  switch (kind) {
    case "csv": return "CSV";
    case "sqlite": return "SQLite";
    case "postgres": return "Postgres";
    case "http": return "HTTP";
    case "vector_store": return "Vector";
    case "neo4j": return "Neo4j";
    case "kf": return "Graph";
    case "iam": return "IAM";
    case "tms": return "TMS";
    case "erp": return "ERP";
    case "finance": return "Finance";
    case "governance": return "Governance";
    default: return kind.toUpperCase();
  }
}

function kindDescription(kind: string): string {
  switch (kind) {
    case "csv": return "Flat-file table on disk";
    case "sqlite": return "Embedded relational DB (also a write target for actions)";
    case "postgres": return "Managed relational DB";
    case "http": return "External REST API";
    case "vector_store": return "Semantic-search store (policy / SOP corpus)";
    case "neo4j": return "Graph database";
    case "kf": return "Knowledge-Fabric inline graph fact (policies, baselines)";
    case "iam": return "Identity & Access Management (actor scope / role facts)";
    case "tms": return "Transportation Management System (shipments, lanes)";
    case "erp": return "ERP system (orders, customer master)";
    case "finance": return "Finance system (cost, accruals)";
    case "governance": return "Governance audit store (prior reviewer decisions)";
    default: return "Registered data source";
  }
}

// =============================================================================
// GlossaryModal — one place to look up every label that appears in the
// envelope: fact badges, source pills, stage names, and actor-scope vocabulary.
// Triggered from the "?" icon in the envelope eyebrow.
// =============================================================================
function GlossaryModal({ onClose }: { onClose: () => void }) {
  // Close on Escape.
  if (typeof document !== "undefined") {
    document.onkeydown = (e) => {
      if (e.key === "Escape") onClose();
    };
  }
  return (
    <div className="glossary-backdrop" onClick={onClose}>
      <div className="glossary-modal" onClick={(e) => e.stopPropagation()}>
        <div className="glossary-header">
          <div>
            <div className="glossary-eyebrow">Reference</div>
            <div className="glossary-title">What these labels mean</div>
          </div>
          <button className="glossary-close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="glossary-body">

          <section>
            <h3>Fact badges</h3>
            <p>Coloured accents that flag a fact needing attention.</p>
            <dl className="glossary-dl">
              <dt><span className="fact-accent-badge risk">EXCEPTION</span></dt>
              <dd>Shipment is flagged: <code>delayed</code>, <code>customs_hold</code>, <code>damage</code>, <code>vessel_change</code>, or <code>port_congestion</code>. Sourced from the <code>exception_flag</code> column of <code>shipments.csv</code>; ~15% of seeded rows carry one. Fact card gets a red left border.</dd>
              <dt><span className="fact-accent-badge warning">CONGESTED</span></dt>
              <dd>Port-level operational friction: high berth wait, active labor action, or weather disruption. Sourced from <code>ports.csv</code> (look for <code>congestion HIGH</code> or the labor/weather flags). Amber accent.</dd>
              <dt><span className="fact-accent-badge premium">PREMIUM SLA</span></dt>
              <dd>Customer order on the highest service tier (typically large penalty per day late). Sourced from the <code>sla_tier</code> column of <code>customer_orders.csv</code>. Gold accent. Often paired with the SLA-risk scenario.</dd>
            </dl>
          </section>

          <section>
            <h3>Role pills</h3>
            <p>Small pills in the fact card's source row that name a card's role in the current scenario, so the eye doesn't have to read the title to know "is this the failing supplier or a proposed swap candidate?". Triggered by the fact's <code>ontology_type</code> (plus the structured <code>status</code> field for the failing-supplier case).</p>
            <dl className="glossary-dl">
              <dt><span className="fact-role-pill fact-role-failing">FAILING</span></dt>
              <dd>The supplier whose distress triggered the case. Set when a <code>Supplier</code> fact has <code>status</code> starting with <code>chapter_11_</code> (bankruptcy filed) or another distress marker. Everything downstream in the case is a response to this event.</dd>
              <dt><span className="fact-role-pill fact-role-proposed-alt">PROPOSED ALT</span></dt>
              <dd>A swap candidate surfaced by an <code>AlternativeSupplier</code> graph walk. <strong>Not yet vetted.</strong> The reviewer must check the qualification state, the relationship vector to the failing supplier (often a shared HoldingCompany), and any sanctions-proximity inheritance before approving any swap.</dd>
              <dt><span className="fact-role-pill fact-role-affected-buyer">AFFECTED BUYER</span></dt>
              <dd>A downstream supplier (tier-1) that depends on the failing tier-N node via <code>SOURCES_FROM</code> edges in the graph. Surfaced by the <code>DownstreamDependent</code> class. Its programs will feel the pain if the failing supplier stops shipping.</dd>
              <dt><span className="fact-role-pill fact-role-at-risk-program">AT-RISK PROGRAM</span></dt>
              <dd>A customer program whose SKUs depend on the failing supplier — reached via <code>Supplier → PO → Product → Program</code> walk. Surfaced by the <code>ProgramImpact</code> class. The summary chip names the revenue at risk and the per-day OTD penalty so the business stake is explicit.</dd>
            </dl>
          </section>

          <section>
            <h3>Hidden-dependency callout</h3>
            <p>An amber strip across the top of a fact card, between the source row and the title. Means: <strong>this entity is reached through 2+ relationship hops in the graph — there is no direct contract, PO, or ownership edge between you and it</strong>. The card carries it whenever the graph resolver tagged the row with <code>tier ≥ 2</code> (upstream supply chain) or <code>hops ≥ 2</code> (indirect relationship path).</p>
            <p>When the resolver also returns a <code>via_path</code>, the strip names the intermediate entity (e.g. <em>"2-hop chain via Northgate Industrial Holdings — no direct contract, PO, or ownership edge"</em>). Inside the knowledge-graph modal, the same chain is drawn in amber so the route is visible end-to-end.</p>
          </section>

          <section>
            <h3>Source pills</h3>
            <p>Every fact carries a pill showing which data source it came from. The left segment is the connector kind, the right segment is the source's friendly name.</p>
            <dl className="glossary-dl">
              <dt><span className="source-pill source-pill-csv"><span className="source-pill-kind">CSV</span><span className="source-pill-name">shipments</span></span></dt>
              <dd>Flat-file table on disk. Read-only.</dd>
              <dt><span className="source-pill source-pill-sqlite"><span className="source-pill-kind">SQLite</span><span className="source-pill-name">logistics</span></span></dt>
              <dd>Embedded relational DB. Also a write target — <code>retender_booking</code> mutates <code>logistics.sqlite</code>.</dd>
              <dt><span className="source-pill source-pill-postgres"><span className="source-pill-kind">Postgres</span><span className="source-pill-name">governance</span></span></dt>
              <dd>Managed relational DB. Same connector pattern as SQLite; swap path is one mapping change.</dd>
              <dt><span className="source-pill source-pill-http"><span className="source-pill-kind">HTTP</span><span className="source-pill-name">jsonplaceholder</span></span></dt>
              <dd>External REST API. Write target for <code>update_eta_to_customer</code>.</dd>
              <dt><span className="source-pill source-pill-vector_store"><span className="source-pill-kind">Vector</span><span className="source-pill-name">policy corpus</span></span></dt>
              <dd>Semantic-search store over policy / SOP markdown excerpts.</dd>
              <dt><span className="source-pill source-pill-neo4j"><span className="source-pill-kind">Neo4j</span><span className="source-pill-name">supply graph</span></span></dt>
              <dd>Graph database for relationship-heavy lookups (Cypher with a read-only safety guard).</dd>
              <dt><span className="source-pill source-pill-kf"><span className="source-pill-kind">Graph</span><span className="source-pill-name">graph</span></span></dt>
              <dd>Knowledge-Fabric inline graph fact — policies, baselines, anything authored directly in a scenario rather than fetched.</dd>
              <dt><span className="source-pill source-pill-iam"><span className="source-pill-kind">IAM</span><span className="source-pill-name">scopes</span></span></dt>
              <dd>Identity & Access Management — the actor's identity and capabilities (see "Actor scopes" below).</dd>
            </dl>
          </section>

          <section>
            <h3>Stage labels</h3>
            <p>Every case moves through up to three stages. Each binds a different slice of context.</p>
            <dl className="glossary-dl">
              <dt><strong>Stage 1 · Policy &amp; scope</strong></dt>
              <dd>Raw name: <code>agent_intake</code>. Binds the active policy + the agent's IAM scopes. Answers: <em>"Is this kind of action permitted, and is this agent allowed to perform it?"</em></dd>
              <dt><strong>Stage 2 · Agent gathered</strong></dt>
              <dd>Raw name: <code>proposal</code>. Binds the operational data the agent needs to either act autonomously or draft a proposal for a reviewer. This is where ontology lookups (Shipment, Booking, Carrier, etc.) run.</dd>
              <dt><strong>Stage 3 · For your decision</strong></dt>
              <dd>Raw name: <code>review</code>. Only present on HITL scenarios. Adds the evidence package a human reviewer needs to judge (prior similar cases, customer SLA, alternate options). The reviewer never sees raw data without this stage's framing.</dd>
            </dl>
          </section>

          <section>
            <h3>Actor scopes</h3>
            <p>The agent acts under a named identity (e.g. <code>agent-logistics-31</code>) with explicit, named capabilities. Think OAuth scopes or AWS IAM policies. Every case records the scopes the agent claimed at execution time — compliance can replay <em>"what was the agent authorized to do when this booking was changed?"</em></p>
            <dl className="glossary-dl">
              <dt><code>logistics.read</code></dt>
              <dd>Look up shipments, carriers, lanes, ports. No side effects. Used by trace / scorecard / port-disruption scenarios.</dd>
              <dt><code>logistics.propose</code></dt>
              <dd>Draft an action (e.g. propose a re-tender) but not execute it. Required by any HITL scenario that ends in human approval.</dd>
              <dt><code>logistics.tender_after_review</code></dt>
              <dd>Execute a booking change ONLY after a human reviewer approves. The actual SQL write only fires when the human clicks Approve.</dd>
              <dt><code>logistics.write_customer_eta</code></dt>
              <dd>Push ETA updates directly to customer systems — the only autonomous-write scope in the current setup. Bounded by guardrail <code>GR-LN-AUTO-ETA-002</code> (variance ≤ 3 days).</dd>
              <dt><code>sc.read / sc.propose / sc.execute_after_review</code></dt>
              <dd>Trade-compliance equivalents. Same propose-then-execute pattern; different domain.</dd>
            </dl>
          </section>

          <section>
            <h3>Confidence labels</h3>
            <p>When the classifier isn't sure, the "Or did you mean…?" row appears with alternatives. Confidence is a 0-1 score from the LLM classifier, rendered as plain English:</p>
            <ul className="glossary-conf-list">
              <li><span className="did-you-mean-conf conf-strong">Strong match</span> — ≥85% confident</li>
              <li><span className="did-you-mean-conf conf-likely">Likely match</span> — 65–84%</li>
              <li><span className="did-you-mean-conf conf-possible">Possible match</span> — 40–64%</li>
              <li><span className="did-you-mean-conf conf-weak">Weak match</span> — &lt;40%</li>
            </ul>
          </section>

        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Phase 3b — promoted-pattern advisory banner
// =============================================================================
function PromotedPatternBanner({ patterns }: { patterns: MatchedPromotedPattern[] }) {
  return (
    <div className="promoted-pattern-banner">
      <div className="promoted-pattern-eyebrow">
        Compounding loop · {patterns.length} promoted pattern{patterns.length === 1 ? "" : "s"} matched
      </div>
      <div className="promoted-pattern-help">
        Patterns the platform learned from prior reviewer behaviour.
        Advisory — you're not bound by them.
      </div>
      {patterns.map((p) => {
        const md = p.metadata || {};
        return (
          <div key={p.id} className="promoted-pattern-row">
            <div className="promoted-pattern-headline">
              <span className={`promoted-pattern-decision ${p.decision_kind}`}>
                {p.decision_kind === "request_more_info" ? "Request more info" : p.decision_kind}
              </span>
              <span className="promoted-pattern-ot">{p.trigger.ontology_type}</span>
              <span className="promoted-pattern-meta">
                · matched {p.matched_fact_count} fact{p.matched_fact_count === 1 ? "" : "s"} on this case
              </span>
            </div>
            <div className="promoted-pattern-body">
              {p.suggested_rationale}
            </div>
            {(md.source_case_count != null && md.source_share_of_kind_pct != null) && (
              <div className="promoted-pattern-source">
                Based on {md.source_case_count} prior case{md.source_case_count === 1 ? "" : "s"} ·{" "}
                {md.source_share_of_kind_pct}% of {p.decision_kind} decisions on this scenario
                {md.promoted_at && ` · promoted ${md.promoted_at.slice(0, 10)}`}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
