// W8 — agent-driven supply-assurance demo surface.
//
// Visual direction: Process Flow (option 5 from docs/agent-ui-options).
// Each phase of the run renders as a "node" in a vertical flow with
// connectors between them. The orchestrator's three findings (tier-1
// buyers / programs at risk / alternates) collapse into a single
// 3-column node so the chain reads cleanly. Sub-agents fan out into a
// 2×2 parallel fork below. Each node preserves the per-card
// "Open in fabric" affordance from the previous timeline view —
// double-click anywhere on a node OR click the corner pill to deep-
// link into the matching Knowledge Fabric view.

import { useEffect, useRef, useState } from "react";
import { AgentEvent, agentRunStart, agentRunStream } from "../api";

interface RunState {
  running: boolean;
  done: boolean;
  events: AgentEvent[];
  error: string | null;
  runId: string | null;
}

const INITIAL: RunState = {
  running: false,
  done: false,
  events: [],
  error: null,
  runId: null,
};

export function AgentRun({ onExit }: { onExit?: () => void }) {
  const [state, setState] = useState<RunState>(INITIAL);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => () => esRef.current?.close(), []);

  const start = async () => {
    try {
      esRef.current?.close();
      setState({ ...INITIAL, running: true });
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
      setState((s) => ({ ...s, running: false, error: err?.message || String(err) }));
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
            step is double-clickable to open the matching fabric view.
          </p>
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

      {state.events.length === 0 && !state.error && (
        <div className="pf-empty">
          Click <strong>Start investigation</strong> above. Each phase will
          land as a node in the process flow below — each node is
          double-clickable to open the matching Knowledge Fabric view.
        </div>
      )}

      {state.events.length > 0 && (
        <ProcessFlow events={state.events} onTraceTo={onTraceTo} />
      )}

      {state.error && (
        <div className="pf-error">⚠ {state.error}</div>
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
}: {
  events: AgentEvent[];
  onTraceTo: (id: string) => void;
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
      {news && <NewsNode ev={news} />}
      {news && (risk || stage === "risk") && <Connector />}
      {risk && <RiskNode ev={risk} />}
      {risk && (investigation || stage === "investigation") && <Connector />}
      {(investigation || tier1 || programs || alternates) && (
        <OrchestratorNode
          investigation={investigation}
          tier1={tier1}
          programs={programs}
          alternates={alternates}
          stage={stage}
        />
      )}
      {(alternates || spawn) && <Connector />}
      {spawn && <ForkHead ev={spawn} />}
      {(spawn || subagents.length > 0) && (
        <SubagentFork
          subagents={subagents}
          onTraceTo={onTraceTo}
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

// One node is a card with a header row (badge + name + time + optional
// fabric link) plus an optional body. Double-click on the node opens
// the fabric link when one is present.
function Node({
  kind,
  badge,
  name,
  time,
  lede,
  fabricLink,
  fabricLinkLabel = "↗ Open in fabric",
  id,
  pulsing,
  children,
}: {
  kind: string;
  badge: string;
  name: string;
  time?: string;
  lede?: string;
  fabricLink?: string | null;
  fabricLinkLabel?: string;
  id?: string;
  pulsing?: boolean;
  children?: React.ReactNode;
}) {
  const onDouble = fabricLink
    ? () => window.open(fabricLink, "_blank", "noreferrer")
    : undefined;
  return (
    <div
      id={id}
      className={
        `pf-node pf-node-${kind}` +
        (fabricLink ? " pf-node-clickable" : "") +
        (pulsing ? " pf-node-pulsing" : "")
      }
      onDoubleClick={onDouble}
      title={fabricLink ? "Double-click to open in the fabric" : undefined}
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
        {fabricLink && (
          <a
            href={fabricLink}
            target="_blank"
            rel="noreferrer"
            className="pf-corner-link"
            onClick={(e) => e.stopPropagation()}
          >
            {fabricLinkLabel}
          </a>
        )}
      </div>
      {children && <div className="pf-body">{children}</div>}
    </div>
  );
}

// =============================================================================
// Node variants
// =============================================================================
function NewsNode({ ev }: { ev: AgentEvent }) {
  const p = ev.payload;
  return (
    <Node
      kind="news"
      badge="📰"
      name="News Feed Monitor"
      time={ev.at.slice(11, 19)}
      lede="Picked up a wire-story matching the watch list."
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

function RiskNode({ ev }: { ev: AgentEvent }) {
  const p = ev.payload;
  const escalatedFrom = p.triggered_by_source;
  return (
    <Node
      kind="risk"
      badge="⚠"
      name="Risk Monitor"
      time={ev.at.slice(11, 19)}
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
}: {
  investigation: AgentEvent | undefined;
  tier1: AgentEvent | undefined;
  programs: AgentEvent | undefined;
  alternates: AgentEvent | undefined;
  stage: string;
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
          link={tier1?.fabric_link}
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
          link={programs?.fabric_link}
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
          link={alternates?.fabric_link}
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
  link,
  id,
  children,
}: {
  eyebrow: string;
  link?: string | null;
  id?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="pf-col" id={id}>
      <div className="pf-col-eyebrow">{eyebrow}</div>
      {children}
      {link && (
        <a
          href={link}
          target="_blank"
          rel="noreferrer"
          className="pf-col-link"
          onClick={(e) => e.stopPropagation()}
        >
          ↗ Open in fabric
        </a>
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
  stage,
}: {
  subagents: AgentEvent[];
  onTraceTo: (id: string) => void;
  stage: string;
}) {
  const byId = new Map(subagents.map((s) => [s.agent_id, s]));
  const pulse = stage === "subagents" || stage === "spawning";
  // Always render all four tiles in 2×2 layout; show pending state when
  // an event hasn't arrived yet so the parallel-fork shape is visible
  // immediately when spawning fires.
  const slots = [
    { id: "distribution_optimizer", name: "Distribution Optimizer", badge: "DO" },
    { id: "alternate_outreach", name: "Alternate Outreach", badge: "AO" },
    { id: "program_manager_notifier", name: "Program Manager Notifier", badge: "PM" },
    { id: "financial_summarizer", name: "Financial Summarizer", badge: "FS" },
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
  pulsing,
}: {
  slot: { id: string; name: string; badge: string };
  ev?: AgentEvent;
  onTraceTo: (id: string) => void;
  pulsing: boolean;
}) {
  const time = ev?.at.slice(11, 19);
  const fabricLink =
    (slot.id === "alternate_outreach" || slot.id === "program_manager_notifier") &&
    ev?.fabric_link
      ? ev.fabric_link
      : null;
  const onDouble = fabricLink
    ? () => window.open(fabricLink, "_blank", "noreferrer")
    : undefined;

  return (
    <div
      className={
        `pf-subnode pf-sub-${slot.id}` +
        (fabricLink ? " pf-node-clickable" : "") +
        (pulsing ? " pf-node-pulsing" : "") +
        (!ev ? " pf-subnode-pending" : "")
      }
      onDoubleClick={onDouble}
      title={fabricLink ? "Double-click to open in the fabric" : undefined}
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
        {fabricLink && (
          <a
            href={fabricLink}
            target="_blank"
            rel="noreferrer"
            className="pf-corner-link"
            onClick={(e) => e.stopPropagation()}
          >
            ↗ Open in fabric
          </a>
        )}
      </div>
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
      <div className="pf-sub-headline">
        Allocation order: <strong>{ranked.map((r) => r.name).join(" → ")}</strong>
      </div>
      <table className="pf-tbl">
        <thead>
          <tr>
            <th>#</th>
            <th>Program</th>
            <th className="num">$M</th>
            <th className="num">$k/day</th>
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
      <div className="pf-sub-headline">
        <strong>${p.total_revenue_at_risk_usd_m}M</strong> revenue at risk ·{" "}
        <strong>${p.total_otd_penalty_usd_k_per_day}k</strong>/day OTD penalty
      </div>
      <table className="pf-tbl">
        <thead>
          <tr>
            <th>Program</th>
            <th className="num">$M</th>
            <th className="num">$k/day</th>
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
          <div className="l">Anchor</div>
          <div className="v">{p.anchor_supplier_id}</div>
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
