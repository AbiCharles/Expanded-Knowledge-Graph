// W8 — agent-driven supply-assurance demo surface.
//
// Visual direction: Process Flow (option 5 from docs/agent-ui-options).
// Each phase of the run renders as a "node" in a vertical flow with
// connectors between them. The orchestrator's three findings (tier-1
// buyers / programs at risk / alternates) collapse into a single
// 3-column node so the chain reads cleanly. Sub-agents fan out into a
// 2×2 parallel fork below.
//
// Per-node "Open in fabric" no longer NAVIGATES away to the fabric's
// /case/aeronova page (which would run the W1–W8 scenario walkthrough
// in the Console). Instead it opens an in-place graph overlay on the
// agent-run page itself, with the process instructions for that step
// surfaced in a side panel. The audience stays in the agent flow;
// the graph pops on top, contextualised by what the agent did.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AgentEvent,
  agentRunStart,
  agentRunStream,
  confirmCase,
  createCase,
  getAeronovaFindings,
  getCase,
  getSupplierSubgraph,
  AeronovaFindings,
  SubgraphResponse,
} from "../api";
import { CaseFull } from "../types";
import { GraphModal } from "./GraphViz";

interface RunState {
  running: boolean;
  done: boolean;
  events: AgentEvent[];
  error: string | null;
  runId: string | null;
  // True while the news-feed pre-roll is playing (the Reuters ticker +
  // BREAKING flash that fires BEFORE the SSE stream's first event is
  // surfaced). The SSE stream itself can already be running underneath
  // — events queue up in `events` and only get rendered once the
  // pre-roll resolves. Sells the "agent is watching a live wire" story
  // before the deterministic investigation flow kicks in.
  prerolling: boolean;
}

const INITIAL: RunState = {
  running: false,
  done: false,
  events: [],
  error: null,
  runId: null,
  prerolling: false,
};

// Decorative aerospace wire-story headlines that scroll across the
// pre-roll ticker. Not real Reuters copy — just plausible-sounding
// supply-chain news so the audience reads it as "a live feed the
// agent is watching." If the demo runs long enough for the ticker
// to fully cycle, the headlines loop seamlessly.
const PRE_ROLL_HEADLINES = [
  "Boeing 787-10 deliveries cleared for resumption · Tulsa final-assembly ramps",
  "Airbus reports Q2 backlog up 4% on A321XLR demand · order book at 8,200",
  "GE Aerospace lifts GEnx production guidance for 2026 H2 on engine TAT gains",
  "Pratt & Whitney expands GTF inspection capacity at five MRO hubs",
  "Lockheed Martin secures Block 70 export approval for two new buyer nations",
  "Rolls-Royce books $1.4B in narrow-body engine MRO contracts for Asia-Pacific",
  "Spirit AeroSystems closes Q2 with fuselage delivery rate restored to plan",
  "FAA grants type certification for Eviation Alice all-electric commuter",
];
// The wire-story that the Risk Monitor matches against the watch list.
// Mirrors the headline the orchestrator emits in the news_source_detected
// event so the pre-roll flows naturally into the news card below it.
const BREAKING_HEADLINE =
  "Czech tier-2 aerospace forging supplier files for Chapter 11 protection";

// Process instructions per step. Surfaced in the side panel of the
// in-place graph overlay so the audience can read what the agent
// actually did to arrive at the graph view they're looking at.
type StepKey =
  | "news"
  | "risk"
  | "tier1"
  | "programs"
  | "alternates"
  | "alt_outreach"
  | "pm_notify";

const STEPS: Record<StepKey, { title: string; lede: string; steps: string[] }> = {
  news: {
    title: "News-feed pickup",
    lede: "News-Feed Monitor watches the supplier-failure watch list and " +
      "raises a hit when a wire-story names a supplier on it.",
    steps: [
      "Reuters wire ingested into the agent's source pipe.",
      "Entity recognition: 'Northwind Forge & Castings' → SUP-021.",
      "Relevance score 0.94 → above 0.80 threshold → escalate.",
      "Hand-off to Risk Monitor with matched supplier_id + headline.",
    ],
  },
  risk: {
    title: "Risk escalation",
    lede: "Risk Monitor classifies the wire-story into a supplier-failure " +
      "event and raises severity for the supplier-assurance orchestrator.",
    steps: [
      "Classify event: chapter_11_filed_2026-06-18 → SUPPLIER_FAILURE.",
      "Resolve supplier: SUP-021 → Northwind Forge & Castings (tier-2).",
      "Severity: HIGH (Chapter 11 → near-term shipment uncertainty).",
      "Open investigation in Supplier Assurance orchestrator.",
    ],
  },
  tier1: {
    title: "Tier-1 buyer discovery",
    lede: "Orchestrator queries the Knowledge Fabric to find every " +
      "supplier that buys directly from the failing tier-2.",
    steps: [
      "POST /api/graph/subgraph { supplier_id: SUP-021, depth: 4 }.",
      "Walk SOURCES_FROM edges INTO the anchor node.",
      "Each source endpoint is a tier-1 buyer of the failing supplier.",
      "Surface tier-1 list (3 buyers) for downstream impact analysis.",
    ],
  },
  programs: {
    title: "Downstream programs at risk",
    lede: "From each tier-1 buyer the orchestrator walks the supply chain " +
      "forward through POs and SKUs to land on the customer programs at risk.",
    steps: [
      "For each tier-1 buyer: walk PLACED → CONTAINS → INCLUDED_IN.",
      "Reach Program terminals (PRG-* nodes).",
      "Filter by customer = Aeronova (the case subject).",
      "Surface 3 flagship programs as the exposed downstream.",
    ],
  },
  alternates: {
    title: "Alternate supplier candidates",
    lede: "Orchestrator looks sideways from the failing supplier — siblings " +
      "under the same holding company, JV partners — for drop-in candidates.",
    steps: [
      "From SUP-021's HoldingCompany, walk OWNS → sibling Suppliers.",
      "Also walk PARTNER_OF for joint-venture alternates.",
      "Annotate each candidate with current qualification state.",
      "Surface 2 candidates: Ironcrest (JV) + Stillwater (shared parent).",
    ],
  },
  alt_outreach: {
    title: "Alternate outreach drafts",
    lede: "Alternate Outreach sub-agent filters the candidate list by " +
      "compliance and drafts the outreach package per surviving candidate.",
    steps: [
      "Pull qualification state for each candidate.",
      "Compliance gate: drop expired (Stillwater Alloys · lapsed 2026-04-15).",
      "Rank survivors by reliability score.",
      "Draft outreach package for Ironcrest Metalworks (primary).",
    ],
  },
  pm_notify: {
    title: "Program-manager notifications",
    lede: "PM Notifier sub-agent pulls the program-manager contact per " +
      "exposed program and drafts a per-program notification.",
    steps: [
      "For each program: lookup MANAGED_BY → ProgramManager.",
      "Pull PO + SKU + revenue context per program.",
      "Draft notification naming the PO + revenue stake.",
      "3 notifications: Mirage, Viper, Comet.",
    ],
  },
};

// Parse the fabric_link URL emitted by the orchestrator into the bits the
// in-place overlay needs (view + focus ids). The orchestrator's URL shape
// is /?launch=aeronova&view=graph|pathways&focus=ID,ID,ID; we read view +
// focus and ignore the rest (no navigation happens — the URL is just data).
function parseFabricLink(
  url: string | null | undefined,
): { view: "network" | "pathways"; focusIds: string[] } | null {
  if (!url) return null;
  try {
    const u = new URL(url, window.location.origin);
    const view = u.searchParams.get("view");
    const focus = u.searchParams.get("focus") || "";
    if (view !== "graph" && view !== "pathways") return null;
    return {
      view: view === "graph" ? "network" : "pathways",
      focusIds: focus.split(",").map((s) => s.trim()).filter(Boolean),
    };
  } catch {
    return null;
  }
}

export function AgentRun({ onExit }: { onExit?: () => void }) {
  const [state, setState] = useState<RunState>(INITIAL);
  const esRef = useRef<EventSource | null>(null);
  // In-place graph overlay. When set, a full-screen modal opens on top
  // of the process flow showing the relevant subgraph with the focus
  // ids called out + a side panel of process instructions.
  const [overlay, setOverlay] = useState<{
    view: "network" | "pathways";
    focusIds: string[];
    step: StepKey;
  } | null>(null);
  // Silently-loaded Aeronova case + findings, used to feed the embedded
  // GraphModal so it gets the same Network + Decision-pathways treatment
  // the fabric shows. Loaded once per page lifetime on the first overlay
  // open and cached for subsequent opens. Promise-cached via a ref so
  // double-fast clicks don't spawn two background cases.
  const [aeronovaCase, setAeronovaCase] = useState<CaseFull | null>(null);
  const [aeronovaFindings, setAeronovaFindings] = useState<AeronovaFindings | null>(null);
  const caseLoadStarted = useRef(false);

  useEffect(() => () => esRef.current?.close(), []);

  // Silent Aeronova case load — fired the first time the audience opens
  // any "Open in fabric" overlay. Stays in the background; the user
  // never sees the Console / FlowStage chrome that would otherwise pop
  // when launching the case. Polls getCase until stages bind so the
  // Decision-pathways tab has its decisionSupport data when rendered.
  useEffect(() => {
    if (!overlay) return;
    if (aeronovaCase) return;
    if (caseLoadStarted.current) return;
    caseLoadStarted.current = true;
    let cancelled = false;
    (async () => {
      try {
        const prompt =
          "Northwind Forge just filed Chapter 11 — assess Aeronova supply assurance";
        const created = await createCase(prompt);
        if (cancelled) return;
        await confirmCase(created.case_id);
        // Poll for stages.bound — give it up to 20s (50 × 400ms).
        for (let i = 0; i < 50; i++) {
          if (cancelled) return;
          await new Promise((r) => setTimeout(r, 400));
          const c = await getCase(created.case_id);
          if (cancelled) return;
          if (c.stages && c.stages.length > 0) {
            setAeronovaCase(c);
            getAeronovaFindings()
              .then((f) => { if (!cancelled) setAeronovaFindings(f); })
              .catch(() => {});
            return;
          }
        }
      } catch (e) {
        console.warn("silent aeronova case load failed:", e);
        caseLoadStarted.current = false; // allow retry on next overlay open
      }
    })();
    return () => { cancelled = true; };
  }, [overlay, aeronovaCase]);

  const start = () => {
    esRef.current?.close();
    // Pre-roll first; SSE deferred until the ticker + BREAKING
    // sequence resolves. With PAUSE_BETWEEN_STAGES bumped on the
    // orchestrator, kicking off SSE on click would queue 4-5 events
    // by the time the pre-roll ends and dump them all at once —
    // breaking the "agent is doing work" reveal cadence. Deferring
    // means each event materialises in the ProcessFlow as the
    // orchestrator emits it.
    setState({ ...INITIAL, running: true, prerolling: true });
  };

  const onPreRollComplete = async () => {
    setState((s) => ({ ...s, prerolling: false }));
    try {
      const { run_id } = await agentRunStart();
      setState((s) => ({ ...s, runId: run_id }));
      const es = agentRunStream(
        run_id,
        (ev) => setState((s) => ({ ...s, events: [...s.events, ev] })),
        () => setState((s) => ({ ...s, running: false, done: true })),
        (err) =>
          setState((s) => ({
            ...s,
            running: false,
            error: err?.message || "stream error",
          })),
      );
      esRef.current = es;
    } catch (err: any) {
      setState((s) => ({
        ...s,
        running: false,
        error: err?.message || String(err),
      }));
    }
  };

  const reset = () => {
    esRef.current?.close();
    setState(INITIAL);
  };

  // Trace handler — used by Distribution Optimizer + Financial
  // Summarizer to scroll the upstream "programs at risk" node into
  // view and pulse it so the audience sees the input chain.
  const onTraceTo = (targetId: string) => {
    const el = document.getElementById(targetId);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("pf-pulse");
    setTimeout(() => el.classList.remove("pf-pulse"), 1400);
  };

  const onOpenGraph = (
    view: "network" | "pathways",
    focusIds: string[],
    step: StepKey,
  ) => {
    setOverlay({ view, focusIds, step });
  };

  // Memoised so AgentGraphOverlay's mount-effect doesn't re-fire on
  // every parent re-render. The orchestrator POSTs aeronova findings
  // only AFTER its asyncio.gather over the 4 sub-agents resolves; if
  // the audience clicks Open-in-fabric the moment PM Notifier lands,
  // the POST may still be in flight. Refetch on every overlay open
  // + retry once after 1.5s so PM names + outreach overlays render
  // reliably on the Decision-pathways tab.
  const refreshFindings = useCallback(() => {
    getAeronovaFindings()
      .then((f) => setAeronovaFindings(f))
      .catch(() => {});
    setTimeout(() => {
      getAeronovaFindings()
        .then((f) => setAeronovaFindings(f))
        .catch(() => {});
    }, 1500);
  }, []);

  return (
    <div className="pf-page">
      <header className="pf-header">
        <div>
          <div className="pf-eyebrow">Agent-driven supply assurance</div>
          <h1 className="pf-title">
            Watch the agents investigate Northwind Forge &amp; Castings
          </h1>
          <p className="pf-sub">
            A risk-monitoring agent picks up a Reuters wire, escalates to
            the Supplier Assurance orchestrator, which queries the
            Knowledge Fabric and spawns four sub-agents in parallel. Each
            step has an "Open in fabric" button to pop the matching
            knowledge-graph view with the process instructions alongside.
          </p>
          <div className="pf-context">
            <span className="pf-context-label">Case subject</span>
            <span>
              <strong>Northwind Forge &amp; Castings</strong> ·{" "}
              <code>SUP-021</code> — a tier-2 aerospace forging supplier
              that just filed Chapter 11. Aeronova (the case customer)
              doesn't buy from it directly, but several of Aeronova's
              tier-1 suppliers do.
            </span>
          </div>
        </div>
        <div className="pf-actions">
          {!state.running && !state.done && (
            <button className="pf-start" onClick={start}>
              ▶ Start investigation
            </button>
          )}
          {state.running && (
            <button className="pf-start running" disabled>
              ⟳ Investigating…
            </button>
          )}
          {state.done && (
            <button className="pf-start" onClick={reset}>
              ↻ Run again
            </button>
          )}
          {onExit && (
            <button className="pf-exit" onClick={onExit}>
              ← Back to fabric
            </button>
          )}
        </div>
      </header>

      {state.prerolling && <PreRoll onComplete={onPreRollComplete} />}

      {!state.prerolling && !state.running && state.events.length === 0 && !state.error && (
        <div className="pf-empty">
          Click <strong>Start investigation</strong> above. Each phase will
          land as a node in the process flow below — click any
          "Open in fabric" pill to pop the matching knowledge-graph view
          right here, with the process instructions in a side panel.
        </div>
      )}
      {!state.prerolling && state.running && state.events.length === 0 && !state.error && (
        <div className="pf-empty pf-empty-waiting">
          ⟳ Connecting to agent orchestrator · waiting for first event…
        </div>
      )}

      {!state.prerolling && state.events.length > 0 && (
        <ProcessFlow
          events={state.events}
          onTraceTo={onTraceTo}
          onOpenGraph={onOpenGraph}
        />
      )}

      {state.error && (
        <div className="pf-error">⚠ {state.error}</div>
      )}

      {overlay && (
        <AgentGraphOverlay
          view={overlay.view}
          focusIds={overlay.focusIds}
          step={overlay.step}
          aeronovaCase={aeronovaCase}
          aeronovaFindings={aeronovaFindings}
          onRefreshFindings={refreshFindings}
          onClose={() => setOverlay(null)}
        />
      )}
    </div>
  );
}

// =============================================================================
// Process Flow — picks out the events that map to flow nodes and renders
// them top-to-bottom with connectors + a parallel fork for sub-agents.
// =============================================================================
function ProcessFlow({
  events,
  onTraceTo,
  onOpenGraph,
}: {
  events: AgentEvent[];
  onTraceTo: (id: string) => void;
  onOpenGraph: (view: "network" | "pathways", focusIds: string[], step: StepKey) => void;
}) {
  const news = events.find((e) => e.type === "news_source_detected");
  const risk = events.find((e) => e.type === "risk_detected");
  const tier1 = events.find((e) => e.type === "tier1_buyers_found");
  const programs = events.find((e) => e.type === "programs_at_risk_identified");
  const alternates = events.find((e) => e.type === "alternates_surfaced");
  const spawn = events.find((e) => e.type === "subagents_spawned");
  const subagents = events.filter((e) => e.type === "subagent_completed");
  const completed = events.find((e) => e.type === "run_completed");
  const investigation = events.find((e) => e.type === "investigation_started");

  // Show a "running" indicator on the next phase that hasn't completed yet.
  const stage =
    completed ? "done"
      : subagents.length === 4 ? "wrap"
      : spawn ? "subagents"
      : alternates ? "spawning"
      : programs ? "alternates"
      : tier1 ? "programs"
      : investigation ? "orchestrator"
      : risk ? "investigation"
      : news ? "risk"
      : "news";

  return (
    <div className="pf-flow">
      {news && <NewsNode ev={news} onOpenGraph={onOpenGraph} />}
      {news && (risk || stage === "risk") && <Connector />}
      {risk && <RiskNode ev={risk} onOpenGraph={onOpenGraph} />}
      {risk && (investigation || stage === "investigation") && <Connector />}
      {(investigation || tier1 || programs || alternates) && (
        <OrchestratorNode
          investigation={investigation}
          tier1={tier1}
          programs={programs}
          alternates={alternates}
          stage={stage}
          onOpenGraph={onOpenGraph}
        />
      )}
      {(alternates || spawn) && <Connector />}
      {spawn && <ForkHead ev={spawn} />}
      {(spawn || subagents.length > 0) && (
        <SubagentFork
          subagents={subagents}
          onTraceTo={onTraceTo}
          onOpenGraph={onOpenGraph}
          stage={stage}
        />
      )}
      {(subagents.length === 4 || completed) && <Connector />}
      {completed && <CompletedNode ev={completed} />}
    </div>
  );
}

// =============================================================================
// Layout primitives
// =============================================================================
function Connector() {
  return <div className="pf-connector" />;
}

// Headline card with badge + name + time. Optional "Open in fabric"
// corner pill (and double-click on the whole card) when an
// onOpenGraph + step is provided.
function Node({
  kind,
  badge,
  name,
  time,
  lede,
  fabricLink,
  fabricStep,
  fabricFocusIds,
  fabricLinkLabel = "↗ Open in fabric",
  id,
  pulsing,
  children,
  onOpenGraph,
}: {
  kind: string;
  badge: string;
  name: string;
  time?: string;
  lede?: string;
  fabricLink?: string | null;
  fabricStep?: StepKey;
  fabricFocusIds?: string[];
  fabricLinkLabel?: string;
  id?: string;
  pulsing?: boolean;
  children?: React.ReactNode;
  onOpenGraph?: (view: "network" | "pathways", focusIds: string[], step: StepKey) => void;
}) {
  const parsed = parseFabricLink(fabricLink);
  const view = parsed?.view ?? "network";
  const focusIds = fabricFocusIds ?? parsed?.focusIds ?? [];
  const canOpen = !!onOpenGraph && !!fabricStep;
  const onOpen = canOpen
    ? () => onOpenGraph!(view, focusIds, fabricStep!)
    : undefined;
  return (
    <div
      id={id}
      className={
        `pf-node pf-node-${kind}` +
        (canOpen ? " pf-node-clickable" : "") +
        (pulsing ? " pf-node-pulsing" : "")
      }
      onDoubleClick={onOpen}
      title={canOpen ? "Double-click to open the matching graph in-place" : undefined}
    >
      <div className="pf-node-head">
        <div className={`pf-badge pf-badge-${kind}`}>{badge}</div>
        <div className="pf-info">
          <div className="pf-name">
            {name}
            {time && <span className="pf-when"> {time}</span>}
          </div>
          {lede && <div className="pf-lede">{lede}</div>}
        </div>
        {canOpen && (
          <button
            type="button"
            className="pf-corner-link"
            onClick={(e) => {
              e.stopPropagation();
              onOpen!();
            }}
          >
            {fabricLinkLabel}
          </button>
        )}
      </div>
      {children && <div className="pf-body">{children}</div>}
    </div>
  );
}

// =============================================================================
// Node variants
// =============================================================================
function NewsNode({
  ev,
  onOpenGraph,
}: {
  ev: AgentEvent;
  onOpenGraph: (view: "network" | "pathways", focusIds: string[], step: StepKey) => void;
}) {
  const p = ev.payload;
  return (
    <Node
      kind="news"
      badge="📰"
      name="News Feed Monitor"
      time={ev.at.slice(11, 19)}
      lede="Picked up a wire-story matching the watch list."
      fabricLink={ev.fabric_link}
      fabricStep="news"
      fabricFocusIds={[p.matched_supplier_id as string].filter(Boolean) as string[]}
      onOpenGraph={onOpenGraph}
    >
      <div className="pf-news-clip">
        <div className="pf-news-src">
          {p.source} · {p.section} · {p.byline} ·{" "}
          {(p.published_at as string)?.slice(0, 10)}
        </div>
        <div className="pf-news-hd">{p.headline}</div>
        <p className="pf-news-lede">{p.lede}</p>
        <div className="pf-news-match">
          Match: <strong>{p.matched_entity}</strong> ·{" "}
          <code>{p.matched_supplier_id}</code> · relevance{" "}
          {(p.relevance_score ?? 0).toFixed(2)}
        </div>
      </div>
    </Node>
  );
}

function RiskNode({
  ev,
  onOpenGraph,
}: {
  ev: AgentEvent;
  onOpenGraph: (view: "network" | "pathways", focusIds: string[], step: StepKey) => void;
}) {
  const p = ev.payload;
  const escalatedFrom = p.triggered_by_source;
  return (
    <Node
      kind="risk"
      badge="⚠"
      name="Risk Monitor"
      time={ev.at.slice(11, 19)}
      fabricLink={ev.fabric_link}
      fabricStep="risk"
      fabricFocusIds={[p.supplier_id as string].filter(Boolean) as string[]}
      onOpenGraph={onOpenGraph}
    >
      {escalatedFrom && (
        <div className="pf-escalated">
          ↑ Escalated from <strong>{escalatedFrom}</strong> wire story above
        </div>
      )}
      <div className="pf-risk-headline">
        <span className="pf-pill pf-pill-no">{p.event}</span>{" "}
        <strong>{p.supplier_name}</strong> <code>({p.supplier_id})</code> ·
        severity <code>{(p.severity || "").toUpperCase()}</code>
      </div>
      {p.summary && <div className="pf-risk-summary">{p.summary}</div>}
    </Node>
  );
}

function OrchestratorNode({
  investigation,
  tier1,
  programs,
  alternates,
  stage,
  onOpenGraph,
}: {
  investigation: AgentEvent | undefined;
  tier1: AgentEvent | undefined;
  programs: AgentEvent | undefined;
  alternates: AgentEvent | undefined;
  stage: string;
  onOpenGraph: (view: "network" | "pathways", focusIds: string[], step: StepKey) => void;
}) {
  const time = investigation?.at.slice(11, 19) || tier1?.at.slice(11, 19) || "";
  const pulsing =
    stage === "orchestrator" || stage === "programs" || stage === "alternates";
  return (
    <Node
      kind="orch"
      badge="SA"
      name="Supplier Assurance · investigation"
      time={time}
      lede="Pulled tier-1 exposure, downstream programs, and alternates from the Knowledge Fabric (one subgraph call · 21 nodes · 20 edges)."
      id="pf-orchestrator"
      pulsing={pulsing}
    >
      <div className="pf-cols">
        <FindingCol
          eyebrow={`Tier-1 buyers · ${(tier1?.payload?.count as number) ?? "—"}`}
          fabricLink={tier1?.fabric_link}
          fabricStep="tier1"
          fabricFocusIds={
            (tier1?.payload?.buyers as any[])?.map((b) => b.supplier_id).filter(Boolean) ?? []
          }
          onOpenGraph={onOpenGraph}
        >
          {tier1 && (
            <ul className="pf-list">
              {(tier1.payload.buyers as any[]).map((b: any) => (
                <li key={b.supplier_id}>
                  {b.name} <code>{b.supplier_id}</code>
                </li>
              ))}
            </ul>
          )}
          {!tier1 && <div className="pf-loading">Walking SOURCES_FROM…</div>}
        </FindingCol>

        <FindingCol
          eyebrow={`Programs at risk · ${(programs?.payload?.count as number) ?? "—"}`}
          fabricLink={programs?.fabric_link}
          fabricStep="programs"
          fabricFocusIds={
            (programs?.payload?.programs as any[])?.map((p) => p.program_id).filter(Boolean) ?? []
          }
          onOpenGraph={onOpenGraph}
          id="agent-card-programs_at_risk_identified"
        >
          {programs && (
            <ul className="pf-list">
              {(programs.payload.programs as any[]).map((p: any) => (
                <li key={p.program_id}>🎯 {p.name}</li>
              ))}
            </ul>
          )}
          {!programs && (
            <div className="pf-loading">Walking PLACED → CONTAINS → INCLUDED_IN…</div>
          )}
        </FindingCol>

        <FindingCol
          eyebrow={`Alternate candidates · ${(alternates?.payload?.count as number) ?? "—"}`}
          fabricLink={alternates?.fabric_link}
          fabricStep="alternates"
          fabricFocusIds={
            (alternates?.payload?.alternates as any[])?.map((a) => a.supplier_id).filter(Boolean) ?? []
          }
          onOpenGraph={onOpenGraph}
        >
          {alternates && (
            <ul className="pf-list">
              {(alternates.payload.alternates as any[]).map((a: any) => {
                const isJV = (a.via || "").includes("joint-venture");
                const isShared = (a.via || "").includes("sibling");
                return (
                  <li key={a.supplier_id}>
                    {isJV && <span className="pf-pill pf-pill-ok">JV</span>}
                    {isShared && (
                      <span className="pf-pill pf-pill-amber">shared parent</span>
                    )}{" "}
                    {a.name} <code>{a.supplier_id}</code>
                  </li>
                );
              })}
            </ul>
          )}
          {!alternates && <div className="pf-loading">Looking up alternates…</div>}
        </FindingCol>
      </div>
    </Node>
  );
}

function FindingCol({
  eyebrow,
  fabricLink,
  fabricStep,
  fabricFocusIds,
  id,
  children,
  onOpenGraph,
}: {
  eyebrow: string;
  fabricLink?: string | null;
  fabricStep?: StepKey;
  fabricFocusIds?: string[];
  id?: string;
  children: React.ReactNode;
  onOpenGraph: (view: "network" | "pathways", focusIds: string[], step: StepKey) => void;
}) {
  const parsed = parseFabricLink(fabricLink);
  const view = parsed?.view ?? "network";
  const ids = fabricFocusIds ?? parsed?.focusIds ?? [];
  const canOpen = !!fabricStep;
  return (
    <div className="pf-col" id={id}>
      <div className="pf-col-eyebrow">{eyebrow}</div>
      {children}
      {canOpen && (
        <button
          type="button"
          className="pf-col-link"
          onClick={(e) => {
            e.stopPropagation();
            onOpenGraph(view, ids, fabricStep!);
          }}
        >
          ↗ Open in fabric
        </button>
      )}
    </div>
  );
}

function ForkHead({ ev }: { ev: AgentEvent }) {
  const count = (ev.payload.subagents as any[])?.length ?? 4;
  return (
    <div className="pf-fork-head">⚡ Spawning {count} sub-agents in parallel</div>
  );
}

function SubagentFork({
  subagents,
  onTraceTo,
  onOpenGraph,
  stage,
}: {
  subagents: AgentEvent[];
  onTraceTo: (id: string) => void;
  onOpenGraph: (view: "network" | "pathways", focusIds: string[], step: StepKey) => void;
  stage: string;
}) {
  const byId = new Map(subagents.map((s) => [s.agent_id, s]));
  const pulse = stage === "subagents" || stage === "spawning";
  // Always render all four tiles in 2×2 layout; show pending state when
  // an event hasn't arrived yet so the parallel-fork shape is visible
  // immediately when spawning fires.
  // Per-slot responsibility text shown ONLY while the tile is pending
  // (i.e. before the sub-agent's completed event has arrived). Tells the
  // audience what each agent is about to do, so the parallel-fork
  // moment isn't four blank tiles. Disappears once the result arrives
  // and the tile renders its full body (Shows / Derived + table).
  const slots: {
    id: string;
    name: string;
    badge: string;
    responsibility: string;
  }[] = [
    {
      id: "distribution_optimizer",
      name: "Distribution Optimizer",
      badge: "DO",
      responsibility:
        "Will rank the 3 exposed programs by revenue + OTD penalty " +
        "to decide which program gets supply priority if alternate " +
        "capacity is constrained.",
    },
    {
      id: "alternate_outreach",
      name: "Alternate Outreach",
      badge: "AO",
      responsibility:
        "Will filter the alternate-supplier candidates through " +
        "compliance, draft the outreach package for the primary " +
        "candidate, and flag any candidate whose qualification has " +
        "lapsed.",
    },
    {
      id: "program_manager_notifier",
      name: "Program Manager Notifier",
      badge: "PM",
      responsibility:
        "Will draft a per-program notification routed to the " +
        "responsible program manager, naming the affected PO and " +
        "revenue at stake.",
    },
    {
      id: "financial_summarizer",
      name: "Financial Summarizer",
      badge: "FS",
      responsibility:
        "Will roll dollar exposure across all exposed programs — " +
        "revenue at risk, daily OTD penalty, and the worst-case " +
        "penalty if mitigation slips.",
    },
  ];
  return (
    <div className="pf-fork">
      {slots.map((slot) => {
        const ev = byId.get(slot.id);
        return (
          <SubagentTile
            key={slot.id}
            slot={slot}
            ev={ev}
            onTraceTo={onTraceTo}
            onOpenGraph={onOpenGraph}
            pulsing={pulse && !ev}
          />
        );
      })}
    </div>
  );
}

function SubagentTile({
  slot,
  ev,
  onTraceTo,
  onOpenGraph,
  pulsing,
}: {
  slot: { id: string; name: string; badge: string; responsibility: string };
  ev?: AgentEvent;
  onTraceTo: (id: string) => void;
  onOpenGraph: (view: "network" | "pathways", focusIds: string[], step: StepKey) => void;
  pulsing: boolean;
}) {
  const time = ev?.at.slice(11, 19);
  // Only Alternate Outreach + PM Notifier get an "Open in fabric"
  // affordance — they're the two sub-agents whose findings overlay
  // directly on the Decision-pathways graph.
  const isAltOut = slot.id === "alternate_outreach";
  const isPM = slot.id === "program_manager_notifier";
  const step: StepKey | undefined = isAltOut
    ? "alt_outreach"
    : isPM
      ? "pm_notify"
      : undefined;
  const parsed = parseFabricLink(ev?.fabric_link);
  const view = parsed?.view ?? "pathways";
  const focusIds =
    isAltOut
      ? [
          ...((ev?.payload?.primary as any[]) || []).map((p) => p.supplier_id),
          ...((ev?.payload?.blocked as any[]) || []).map((p) => p.supplier_id),
        ].filter(Boolean)
      : isPM
        ? ((ev?.payload?.notifications as any[]) || [])
            .map((n) => n.program_id)
            .filter(Boolean)
        : [];
  const canOpen = !!ev && !!step;
  const onOpen = canOpen
    ? () => onOpenGraph(view, focusIds, step!)
    : undefined;

  return (
    <div
      className={
        `pf-subnode pf-sub-${slot.id}` +
        (canOpen ? " pf-node-clickable" : "") +
        (pulsing ? " pf-node-pulsing" : "") +
        (!ev ? " pf-subnode-pending" : "")
      }
      onDoubleClick={onOpen}
      title={canOpen ? "Double-click to open the matching graph in-place" : undefined}
    >
      <div className="pf-sub-head">
        <div className={`pf-badge pf-badge-${slot.id}`}>{slot.badge}</div>
        <div className="pf-info">
          <div className="pf-name">
            {slot.name}
            {time && <span className="pf-when"> {time}</span>}
            {!ev && <span className="pf-pending"> · pending</span>}
          </div>
        </div>
        {canOpen && (
          <button
            type="button"
            className="pf-corner-link"
            onClick={(e) => {
              e.stopPropagation();
              onOpen!();
            }}
          >
            ↗ Open in fabric
          </button>
        )}
      </div>
      {!ev && (
        <div className="pf-sub-pending-body">
          <div className="pf-sub-pending-label">Responsibility</div>
          <p className="pf-sub-pending-text">{slot.responsibility}</p>
        </div>
      )}
      {ev && (
        <div className="pf-sub-body">
          {slot.id === "distribution_optimizer" && (
            <DistOptBody ev={ev} onTraceTo={onTraceTo} />
          )}
          {slot.id === "alternate_outreach" && <AltOutreachBody ev={ev} />}
          {slot.id === "program_manager_notifier" && <PMNotifierBody ev={ev} />}
          {slot.id === "financial_summarizer" && (
            <FinSummaryBody ev={ev} onTraceTo={onTraceTo} />
          )}
        </div>
      )}
    </div>
  );
}

// Two-line explainer block placed at the top of every sub-agent body:
// "Shows" = what the tile is showing the audience; "Derived" = how the
// agent produced it (inputs / logic). Keeps the demo self-narrating so
// Naresh doesn't have to explain every card from cold.
function Derivation({ shows, derived }: { shows: string; derived: string }) {
  return (
    <div className="pf-sub-derivation">
      <div>
        <span className="pf-sub-derivation-label">Shows</span>
        <span className="pf-sub-derivation-text">{shows}</span>
      </div>
      <div>
        <span className="pf-sub-derivation-label">Derived</span>
        <span className="pf-sub-derivation-text">{derived}</span>
      </div>
    </div>
  );
}

function DistOptBody({
  ev,
  onTraceTo,
}: {
  ev: AgentEvent;
  onTraceTo: (id: string) => void;
}) {
  const ranked = (ev.payload.ranked as any[]) || [];
  return (
    <>
      <Derivation
        shows="Supply allocation order across the 3 exposed programs if alternate capacity is constrained."
        derived="Sort programs by revenue stake (biggest dollars first); OTD penalty $/day breaks ties."
      />
      <div className="pf-sub-headline">
        Allocation order: <strong>{ranked.map((r) => r.name).join(" → ")}</strong>
      </div>
      <table className="pf-tbl">
        <thead>
          <tr>
            <th>#</th>
            <th>Program</th>
            <th className="num">
              Revenue
              <div className="pf-tbl-unit">($M)</div>
            </th>
            <th className="num">
              OTD penalty
              <div className="pf-tbl-unit">($k/day)</div>
            </th>
          </tr>
        </thead>
        <tbody>
          {ranked.map((r, i) => (
            <tr key={r.program_id || i}>
              <td>{i + 1}</td>
              <td>{r.name}</td>
              <td className="num">{r.revenue_usd_m}</td>
              <td className="num">{r.otd_penalty_usd_k_per_day}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        type="button"
        className="pf-trace"
        onClick={() => onTraceTo("agent-card-programs_at_risk_identified")}
      >
        ↗ Trace inputs back to the orchestrator's findings
      </button>
    </>
  );
}

function AltOutreachBody({ ev }: { ev: AgentEvent }) {
  const primary = (ev.payload.primary as any[]) || [];
  const blocked = (ev.payload.blocked as any[]) || [];
  return (
    <>
      <Derivation
        shows="Which alternate-supplier candidates pass compliance (PRIMARY) and which are blocked, with the blocking reason."
        derived="Pull qualification state per candidate from kf:graph; expired qualifications drop to BLOCKED; survivors sorted by reliability score."
      />
      {primary.length > 0 && (
        <div className="pf-row">
          <span className="pf-pill pf-pill-ok">PRIMARY</span>{" "}
          <strong>{primary.map((p) => p.name).join(", ")}</strong>
          {primary[0]?.via && (
            <div className="pf-row-sub">via {primary[0].via}</div>
          )}
        </div>
      )}
      {blocked.length > 0 && (
        <div className="pf-row">
          <span className="pf-pill pf-pill-no">BLOCKED</span>{" "}
          <strong>{blocked.map((b) => b.name).join(", ")}</strong>
          {blocked[0]?.reason && (
            <div className="pf-row-sub warn">{blocked[0].reason}</div>
          )}
        </div>
      )}
    </>
  );
}

function PMNotifierBody({ ev }: { ev: AgentEvent }) {
  const notifications = (ev.payload.notifications as any[]) || [];
  return (
    <>
      <Derivation
        shows="Per-program notification draft routed to the responsible program manager, naming the affected PO + revenue at stake."
        derived="For each exposed program: lookup MANAGED_BY → ProgramManager in kf:graph; PO + revenue context from the CONTAINS → INCLUDED_IN walk."
      />
      <div className="pf-sub-headline">
        {notifications.length} notification{notifications.length === 1 ? "" : "s"} drafted:
      </div>
      <ul className="pf-list">
        {notifications.map((n: any) => (
          <li key={n.program_id}>
            📨 {n.to} · <code>{n.program_name}</code>
          </li>
        ))}
      </ul>
    </>
  );
}

function FinSummaryBody({
  ev,
  onTraceTo,
}: {
  ev: AgentEvent;
  onTraceTo: (id: string) => void;
}) {
  const p = ev.payload;
  const breakdown = (p.breakdown as any[]) || [];
  return (
    <>
      <Derivation
        shows="Dollar roll-up across all exposed programs — revenue at risk, daily OTD penalty, and the worst-case penalty if mitigation slips."
        derived="Σ(program revenue), Σ(OTD penalty $/day), and (penalty $/day × days-to-mitigate-worst-case). Per-program rows from the same finding the Distribution Optimizer ranked."
      />
      <div className="pf-sub-headline">
        <strong>${p.total_revenue_at_risk_usd_m}M</strong> revenue at risk ·{" "}
        <strong>${p.total_otd_penalty_usd_k_per_day}k</strong>/day OTD penalty
      </div>
      <table className="pf-tbl">
        <thead>
          <tr>
            <th>Program</th>
            <th className="num">
              Revenue
              <div className="pf-tbl-unit">($M)</div>
            </th>
            <th className="num">
              OTD penalty
              <div className="pf-tbl-unit">($k/day)</div>
            </th>
          </tr>
        </thead>
        <tbody>
          {breakdown.map((b: any) => (
            <tr key={b.program_id || b.name}>
              <td>{b.name}</td>
              <td className="num">{b.revenue_usd_m}</td>
              <td className="num">{b.otd_penalty_usd_k_per_day}</td>
            </tr>
          ))}
          <tr className="pf-tbl-total">
            <td>TOTAL</td>
            <td className="num">{p.total_revenue_at_risk_usd_m}</td>
            <td className="num">{p.total_otd_penalty_usd_k_per_day}</td>
          </tr>
        </tbody>
      </table>
      <div className="pf-formula">
        Worst-case = ${p.total_otd_penalty_usd_k_per_day}k/day ×{" "}
        {p.days_to_mitigate_worst_case} days = ${p.worst_case_penalty_usd_m}M
      </div>
      <button
        type="button"
        className="pf-trace"
        onClick={() => onTraceTo("agent-card-programs_at_risk_identified")}
      >
        ↗ Trace inputs back to the orchestrator's findings
      </button>
    </>
  );
}

function CompletedNode({ ev }: { ev: AgentEvent }) {
  const p = ev.payload;
  return (
    <div className="pf-summary">
      <h3 className="pf-summary-eyebrow">✓ Run completed</h3>
      <p className="pf-summary-lede">
        Investigation closed. {p.tier1_buyer_count} tier-1 buyer(s),{" "}
        {p.programs_at_risk_count} program(s) at risk, {p.alternate_count}{" "}
        alternate candidate(s). Findings posted to the fabric; pathway graph
        now overlays PM names + outreach status on the matching terminals.
      </p>
      <div className="pf-stats">
        <div className="pf-stat">
          <div className="l">Investigation focus</div>
          <div className="v">Northwind Forge</div>
          <div className="pf-stat-sub">
            <code>{p.anchor_supplier_id}</code> · failing tier-2
          </div>
        </div>
        <div className="pf-stat">
          <div className="l">Tier-1 buyers</div>
          <div className="v">{p.tier1_buyer_count}</div>
        </div>
        <div className="pf-stat">
          <div className="l">Programs at risk</div>
          <div className="v">{p.programs_at_risk_count}</div>
        </div>
        <div className="pf-stat">
          <div className="l">Alternates</div>
          <div className="v">{p.alternate_count}</div>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// In-place graph overlay
// =============================================================================
// Full-screen overlay on the agent-run page. Left: process instructions
// describing what the agent did to surface this view. Right: the SAME
// GraphModal the fabric uses (embedded mode, no backdrop / portal), so
// the cytoscape look-and-feel, side legend, layout dropdown, Network /
// Decision-pathways tab strip, ontology-class colors, and all the
// pathway highlighting match the fabric exactly. The Aeronova case is
// loaded silently in the background by AgentRun so the embedded
// GraphModal's Pathways tab gets its decisionSupport data without the
// audience seeing the case-launch chrome.
// ----------------------------------------------------------------------------
const ANCHOR_SUPPLIER_ID = "SUP-021";

function AgentGraphOverlay({
  view,
  focusIds,
  step,
  aeronovaCase,
  aeronovaFindings,
  onRefreshFindings,
  onClose,
}: {
  view: "network" | "pathways";
  focusIds: string[];
  step: StepKey;
  aeronovaCase: CaseFull | null;
  aeronovaFindings: AeronovaFindings | null;
  onRefreshFindings: () => void;
  onClose: () => void;
}) {
  const [data, setData] = useState<SubgraphResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Refetch the orchestrator's findings each time the overlay opens
  // — they're POSTed by the orchestrator AFTER its asyncio.gather
  // resolves, which can race with the user clicking Open-in-fabric
  // on PM Notifier. The parent does the actual setState; this just
  // pokes it.
  useEffect(() => {
    onRefreshFindings();
  }, [onRefreshFindings]);

  // One-shot subgraph fetch on mount. Same endpoint the fabric's
  // GraphPanel uses, so the embedded GraphModal sees the same
  // rawNodes/rawEdges it would in the case page.
  useEffect(() => {
    let cancelled = false;
    setError(null);
    getSupplierSubgraph(ANCHOR_SUPPLIER_ID)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError((e as Error).message); });
    return () => { cancelled = true; };
  }, []);

  // Close on Escape so the audience can keep clicking through the flow.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const instructions = STEPS[step];
  const viewLabel = view === "network" ? "Network" : "Decision pathways";
  // Pathways view needs the case data (decisionSupport reads from
  // active.stages); Network view doesn't. So gate Pathways on the
  // silent case load, but let Network render the moment subgraph
  // arrives.
  const pathwaysReady = !!aeronovaCase;
  const isLoading = !data || (view === "pathways" && !pathwaysReady);

  // Hidden-dependency path passed into GraphModal — same derivation
  // GraphPanel does in the fabric (anchor + alternates + via nodes).
  const hiddenDepPath = (() => {
    if (!aeronovaCase) return [ANCHOR_SUPPLIER_ID];
    const ids = new Set<string>();
    ids.add(ANCHOR_SUPPLIER_ID);
    for (const stage of aeronovaCase.stages ?? []) {
      for (const fact of stage.facts ?? []) {
        if (fact.ontology_type !== "AlternativeSupplier") continue;
        if (fact.id) ids.add(fact.id);
        if ((fact as any).via_node_id) ids.add((fact as any).via_node_id);
      }
    }
    return Array.from(ids);
  })();

  return (
    <div className="pf-overlay" role="dialog" aria-modal="true">
      <div className="pf-overlay-backdrop" onClick={onClose} />
      <div className="pf-overlay-shell">
        <header className="pf-overlay-head">
          <div>
            <div className="pf-overlay-eyebrow">
              Knowledge Fabric · {viewLabel}
            </div>
            <h2 className="pf-overlay-title">{instructions.title}</h2>
          </div>
          <button type="button" className="pf-overlay-close" onClick={onClose}>
            ✕ Close
          </button>
        </header>
        <div className="pf-overlay-body">
          <aside className="pf-instructions">
            <div className="pf-instructions-eyebrow">Process instructions</div>
            <p className="pf-instructions-lede">{instructions.lede}</p>
            <ol className="pf-instructions-list">
              {instructions.steps.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
            {focusIds.length > 0 && (
              <div className="pf-instructions-focus">
                <div className="pf-instructions-focus-eyebrow">Called out on graph</div>
                <ul>
                  {focusIds.map((id) => (
                    <li key={id}><code>{id}</code></li>
                  ))}
                </ul>
              </div>
            )}
            {view === "pathways" && !pathwaysReady && (
              <div className="pf-instructions-note">
                ⟳ Loading decision-pathways data from the fabric…
              </div>
            )}
          </aside>
          <div className="pf-graph-pane">
            {error && <div className="pf-graph-error">⚠ {error}</div>}
            {isLoading && !error && (
              <div className="pf-graph-loading">
                {!data
                  ? "Loading supplier subgraph…"
                  : "Loading decision-pathways data…"}
              </div>
            )}
            {data && !isLoading && (
              <GraphModal
                embedded
                title="Knowledge graph"
                subtitle={`${ANCHOR_SUPPLIER_ID} · Northwind Forge & Castings`}
                explainer={
                  "The corporate ownership + supplier network around Northwind " +
                  "Forge — the failing tier-2 supplier this investigation centres " +
                  "on. Pulled live from Neo4j. Each node is a real entity " +
                  "(supplier, holding company, program, product, PO) and each " +
                  "line is a real relationship between them."
                }
                rawNodes={data.nodes}
                rawEdges={data.edges}
                defaultLayout="dagre"
                onClose={onClose}
                loading={!data}
                error={error}
                active={aeronovaCase}
                initialViewMode={view}
                hiddenDepPath={hiddenDepPath}
                aeronovaFindings={aeronovaFindings}
                focusIds={focusIds}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Pre-roll — Reuters ticker that builds anticipation before the SSE stream
// surfaces. Three phases on a ~10.4s timeline:
//   - ticker:   3.0s — red "LIVE · REUTERS WIRE" badge + horizontally
//               scrolling stream of benign aerospace headlines
//   - breaking: 7.0s — bar flashes red, "BREAKING" badge replaces "LIVE",
//               Northwind headline drops in; held long enough for the
//               audience to read both the headline AND the match caption
//               ("Northwind Forge · SUP-021 · relevance 0.94 · escalating
//               to Risk Monitor…") before the agent flow takes over
//   - drop:     0.4s — bar slides up out of frame, then onComplete fires
//               and AgentRun hands off to ProcessFlow
// All animation is CSS-driven (transforms + keyframes); JS only flips
// the phase class on a setTimeout, so there's no rAF jank during the
// live demo.
// =============================================================================
function PreRoll({ onComplete }: { onComplete: () => void }) {
  const [phase, setPhase] = useState<"ticker" | "breaking" | "drop">("ticker");

  useEffect(() => {
    const t1 = setTimeout(() => setPhase("breaking"), 3000);
    const t2 = setTimeout(() => setPhase("drop"), 10000);
    const t3 = setTimeout(() => onComplete(), 10400);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
    };
  }, [onComplete]);

  return (
    <div className={`pf-preroll pf-preroll-${phase}`}>
      <div className="pf-preroll-bar">
        <div className="pf-preroll-badge">
          {phase === "ticker" ? (
            <>
              <span className="pf-preroll-badge-dot" /> LIVE · REUTERS WIRE
            </>
          ) : (
            <>⚠ BREAKING</>
          )}
        </div>
        {phase === "ticker" && (
          <div className="pf-preroll-track">
            <div className="pf-preroll-stream">
              {/* Render the headline list TWICE so the marquee can
                  translate -50% without exposing the seam. The CSS
                  scroll keyframe matches this halving. */}
              {[...PRE_ROLL_HEADLINES, ...PRE_ROLL_HEADLINES].map((h, i) => (
                <span key={i} className="pf-preroll-item">
                  · {h}
                </span>
              ))}
            </div>
          </div>
        )}
        {phase !== "ticker" && (
          <div className="pf-preroll-breaking">{BREAKING_HEADLINE}</div>
        )}
        <div className="pf-preroll-time">
          {new Date().toISOString().slice(11, 19)} UTC
        </div>
      </div>
      {phase === "ticker" && (
        <div className="pf-preroll-caption">
          News Feed Monitor is watching the wire · matching against the
          supplier watch list…
        </div>
      )}
      {phase !== "ticker" && (
        <div className="pf-preroll-caption pf-preroll-caption-match">
          ⚡ Match · <strong>Northwind Forge &amp; Castings (SUP-021)</strong> ·
          relevance 0.94 · escalating to Risk Monitor…
        </div>
      )}
    </div>
  );
}
