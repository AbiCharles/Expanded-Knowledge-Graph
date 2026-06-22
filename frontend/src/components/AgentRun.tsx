// W8 — agent-driven supply-assurance demo surface.
//
// Renders a timeline of events streamed from the agent_orchestrator
// companion service. The page is intentionally minimal: a "Start
// investigation" button at the top, a chronological feed of timeline
// cards in the middle, a sub-agent status rail on the right, and a
// "Walk through the fabric" panel that lands once `run_completed`
// fires (one button per finding, opens the existing fabric in a new
// tab — this is the Naresh handoff).

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

const SUBAGENTS = [
  { id: "distribution_optimizer", name: "Distribution Optimizer" },
  { id: "alternate_outreach", name: "Alternate Outreach" },
  { id: "program_manager_notifier", name: "Program Manager Notifier" },
  { id: "financial_summarizer", name: "Financial Impact Summarizer" },
];

export function AgentRun({ onExit }: { onExit?: () => void }) {
  const [state, setState] = useState<RunState>(INITIAL);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    return () => {
      esRef.current?.close();
    };
  }, []);

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

  // Per sub-agent: status pill in the right rail. Started → progress → done.
  const subagentStatus = (sid: string): "idle" | "running" | "done" => {
    const last = [...state.events].reverse().find((e) => e.agent_id === sid);
    if (!last) return "idle";
    if (last.type === "subagent_completed") return "done";
    return "running";
  };

  const completed = state.events.find((e) => e.type === "run_completed");
  const walkthroughLinks: { label: string; url: string }[] =
    (completed?.payload?.walkthrough_links as any[] | undefined) || [];

  return (
    <div className="agent-run">
      <header className="agent-run-header">
        <div>
          <div className="agent-run-eyebrow">Agent-driven supply assurance</div>
          <h1 className="agent-run-title">
            Watch the agents investigate Northwind Forge & Castings
          </h1>
          <p className="agent-run-sub">
            A risk-monitoring agent detected the Chapter-11 filing. The
            Supplier Assurance orchestrator now investigates by querying
            the Knowledge Fabric, then spawns four sub-agents in parallel.
            After the run completes, open the fabric to walk through the
            underlying components.
          </p>
        </div>
        <div className="agent-run-actions">
          {!state.running && !state.done && (
            <button className="agent-run-start" onClick={start}>
              ▶ Start investigation
            </button>
          )}
          {state.running && (
            <button className="agent-run-start running" disabled>
              ⟳ Investigating…
            </button>
          )}
          {state.done && (
            <button className="agent-run-start" onClick={reset}>
              ↻ Run again
            </button>
          )}
          {onExit && (
            <button className="agent-run-exit" onClick={onExit}>
              ← Back to fabric
            </button>
          )}
        </div>
      </header>

      <div className="agent-run-body">
        <div className="agent-run-timeline">
          {state.events.length === 0 && !state.error && (
            <div className="agent-run-empty">
              Click <strong>Start investigation</strong> above. The
              orchestrator will emit a timeline of events as the agents
              work — each fabric query carries a deep-link you can click
              to see the underlying component in the Knowledge Fabric.
            </div>
          )}
          {state.events.map((ev, i) => (
            <EventCard
              key={i}
              ev={ev}
              cardId={cardIdFor(ev, i)}
              onTraceTo={(targetId) => {
                const el = document.getElementById(targetId);
                if (!el) return;
                el.scrollIntoView({ behavior: "smooth", block: "center" });
                el.classList.add("agent-run-card-pulse");
                setTimeout(
                  () => el.classList.remove("agent-run-card-pulse"),
                  1400,
                );
              }}
            />
          ))}
          {state.error && (
            <div className="agent-run-error">⚠ {state.error}</div>
          )}
          {completed && walkthroughLinks.length > 0 && (
            <div className="agent-run-walkthrough">
              <div className="agent-run-walkthrough-eyebrow">
                Walk through the fabric
              </div>
              <p className="agent-run-walkthrough-lead">
                The agents are done. Now open the Knowledge Fabric to
                walk the audience through each component — the same
                facts the orchestrator just pulled.
              </p>
              <div className="agent-run-walkthrough-buttons">
                {walkthroughLinks.map((l) => (
                  <a
                    key={l.url}
                    href={l.url}
                    target="_blank"
                    rel="noreferrer"
                    className="agent-run-walkthrough-btn"
                  >
                    {l.label} ↗
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>

        <aside className="agent-run-rail">
          <div className="agent-run-rail-section">
            <div className="agent-run-rail-label">Risk Monitor</div>
            <div className="agent-run-rail-row">
              <span
                className={
                  "agent-run-rail-pill " +
                  (state.events.some((e) => e.type === "risk_detected")
                    ? "done"
                    : "idle")
                }
              >
                {state.events.some((e) => e.type === "risk_detected")
                  ? "✓ Triggered"
                  : "Idle"}
              </span>
            </div>
          </div>
          <div className="agent-run-rail-section">
            <div className="agent-run-rail-label">
              Supplier Assurance Orchestrator
            </div>
            <div className="agent-run-rail-row">
              <span
                className={
                  "agent-run-rail-pill " +
                  (state.events.some((e) => e.type === "alternates_surfaced")
                    ? "done"
                    : state.events.some(
                        (e) => e.type === "investigation_started",
                      )
                    ? "running"
                    : "idle")
                }
              >
                {state.events.some((e) => e.type === "alternates_surfaced")
                  ? "✓ Investigation complete"
                  : state.events.some(
                      (e) => e.type === "investigation_started",
                    )
                  ? "⟳ Investigating…"
                  : "Idle"}
              </span>
            </div>
          </div>
          <div className="agent-run-rail-section">
            <div className="agent-run-rail-label">Sub-agents (parallel)</div>
            {SUBAGENTS.map((sa) => {
              const s = subagentStatus(sa.id);
              return (
                <div key={sa.id} className="agent-run-rail-row">
                  <span className={"agent-run-rail-pill " + s}>
                    {s === "done" ? "✓" : s === "running" ? "⟳" : "·"}
                  </span>
                  <span className="agent-run-rail-name">{sa.name}</span>
                </div>
              );
            })}
          </div>
        </aside>
      </div>
    </div>
  );
}

// Stable card-id resolver so the trace links can scroll-to + pulse the
// upstream finding card. We use the event type for findings that are
// unique in the timeline (programs_at_risk_identified, etc.), and
// fall back to the event index for repeats.
function cardIdFor(ev: AgentEvent, index: number): string {
  if (
    ev.type === "programs_at_risk_identified" ||
    ev.type === "fabric_response" ||
    ev.type === "news_source_detected"
  ) {
    return `agent-card-${ev.type}`;
  }
  return `agent-card-${index}`;
}

// =============================================================================
// Timeline event card — one variant per event type.
// =============================================================================
function EventCard({
  ev,
  cardId,
  onTraceTo,
}: {
  ev: AgentEvent;
  cardId: string;
  onTraceTo: (targetId: string) => void;
}) {
  const time = ev.at.slice(11, 19);
  switch (ev.type) {
    case "news_source_detected":
      return (
        <Card kind="news" time={time} agent={ev.payload.agent_name} id={cardId}>
          <div className="agent-run-news-pill">
            📰 {ev.payload.source} · {ev.payload.section}
          </div>
          <div className="agent-run-news-headline">{ev.payload.headline}</div>
          <div className="agent-run-news-meta">
            {ev.payload.byline} · {ev.payload.published_at?.slice(0, 10)}
          </div>
          <p className="agent-run-news-lede">{ev.payload.lede}</p>
          <div className="agent-run-news-match">
            Matched entity: <strong>{ev.payload.matched_entity}</strong>{" "}
            <code>({ev.payload.matched_supplier_id})</code> · relevance{" "}
            {(ev.payload.relevance_score ?? 0).toFixed(2)}
          </div>
        </Card>
      );
    case "risk_detected":
      return (
        <Card kind="risk" time={time} agent={ev.payload.agent_name} id={cardId}>
          {ev.payload.triggered_by_source && (
            <div className="agent-run-risk-connector">
              ↑ Escalated from <strong>{ev.payload.triggered_by_source}</strong>{" "}
              wire story above
            </div>
          )}
          <div className="agent-run-card-headline">
            ⚠ {ev.payload.event} · {ev.payload.supplier_name} (
            {ev.payload.supplier_id})
          </div>
          <div className="agent-run-card-body">{ev.payload.summary}</div>
        </Card>
      );
    case "investigation_started":
      return (
        <Card kind="orchestrator" time={time} agent={ev.payload.agent_name}>
          <div className="agent-run-card-headline">Investigation opened</div>
          <div className="agent-run-card-body">{ev.payload.scope}</div>
        </Card>
      );
    case "agent_thinking":
      return (
        <Card kind="thinking" time={time} agent={agentNameOf(ev)}>
          <div className="agent-run-card-body italic">
            <em>{ev.payload.text}</em>
          </div>
        </Card>
      );
    case "fabric_query":
      return (
        <Card
          kind="fabric-query"
          time={time}
          agent={ev.payload.agent_name}
          fabricLink={ev.fabric_link}
        >
          <div className="agent-run-card-headline">
            🌐 Querying fabric · <code>{ev.payload.endpoint}</code>
          </div>
          <div className="agent-run-card-body">{ev.payload.description}</div>
          <div className="agent-run-card-code">
            {JSON.stringify(ev.payload.request, null, 2)}
          </div>
          {ev.fabric_link && (
            <a
              href={ev.fabric_link}
              target="_blank"
              rel="noreferrer"
              className="agent-run-card-link"
            >
              Open the fabric at this view ↗
            </a>
          )}
        </Card>
      );
    case "fabric_response":
      return (
        <Card
          kind="fabric-response"
          time={time}
          agent="Knowledge Fabric"
          id={cardId}
          fabricLink={ev.fabric_link}
        >
          <div className="agent-run-card-headline">
            ✓ Fabric responded · {ev.payload.node_count} nodes,{" "}
            {ev.payload.edge_count} edges
          </div>
          <div className="agent-run-card-body">
            stats:{" "}
            <code>
              {Object.entries(ev.payload.stats || {})
                .map(([k, v]) => `${k}=${v}`)
                .join(" · ")}
            </code>
          </div>
        </Card>
      );
    case "tier1_buyers_found":
      return (
        <Card
          kind="finding"
          time={time}
          agent={ev.payload.agent_name}
          fabricLink={ev.fabric_link}
        >
          <div className="agent-run-card-headline">
            🏭 {ev.payload.count} tier-1 buyer(s) source from the failing
            supplier
          </div>
          <ul className="agent-run-card-list">
            {(ev.payload.buyers as any[]).map((b: any) => (
              <li key={b.supplier_id}>
                <strong>{b.name}</strong>{" "}
                <code>({b.supplier_id})</code>
              </li>
            ))}
          </ul>
        </Card>
      );
    case "programs_at_risk_identified":
      return (
        <Card
          kind="finding"
          time={time}
          agent={ev.payload.agent_name}
          id={cardId}
          fabricLink={ev.fabric_link}
        >
          <div className="agent-run-card-headline">
            🎯 {ev.payload.count} downstream program(s) at risk
          </div>
          <ul className="agent-run-card-list">
            {(ev.payload.programs as any[]).map((p: any) => (
              <li key={p.program_id}>
                <strong>{p.name}</strong>
              </li>
            ))}
          </ul>
        </Card>
      );
    case "alternates_surfaced":
      return (
        <Card
          kind="finding"
          time={time}
          agent={ev.payload.agent_name}
          fabricLink={ev.fabric_link}
        >
          <div className="agent-run-card-headline">
            🔁 {ev.payload.count} alternate supplier candidate(s) surfaced
          </div>
          <ul className="agent-run-card-list">
            {(ev.payload.alternates as any[]).map((a: any) => (
              <li key={a.supplier_id}>
                <strong>{a.name}</strong>{" "}
                <code>({a.supplier_id})</code> · {a.via}
              </li>
            ))}
          </ul>
        </Card>
      );
    case "subagents_spawned":
      return (
        <Card kind="spawn" time={time} agent={ev.payload.agent_name}>
          <div className="agent-run-card-headline">
            ⚡ Spawning {ev.payload.subagents.length} sub-agents in parallel
          </div>
          <ul className="agent-run-card-list">
            {(ev.payload.subagents as any[]).map((sa: any) => (
              <li key={sa.id}>{sa.name}</li>
            ))}
          </ul>
        </Card>
      );
    case "subagent_started":
      // Suppress — the right-rail status panel already shows each
      // sub-agent transitioning idle → running → done as the events
      // arrive. A row in the timeline for "starting…" would just
      // clutter what's about to be a "completed" card a moment later.
      return null;
    case "subagent_completed":
      return (
        <SubagentResultCard
          ev={ev}
          time={time}
          cardId={cardId}
          onTraceTo={onTraceTo}
        />
      );
    case "run_completed":
      return (
        <Card kind="complete" time={time} agent="Orchestrator">
          <div className="agent-run-card-headline">
            ✓ Investigation complete
          </div>
          <div className="agent-run-card-body">
            <strong>{ev.payload.anchor_supplier_name}</strong> (
            {ev.payload.anchor_supplier_id}) ·{" "}
            {ev.payload.tier1_buyer_count} tier-1 buyer(s) ·{" "}
            {ev.payload.programs_at_risk_count} program(s) at risk ·{" "}
            {ev.payload.alternate_count} alternate candidate(s).
          </div>
        </Card>
      );
    case "error":
      return (
        <div className="agent-run-error">
          <span>⚠ {ev.agent_id} · {ev.payload.message}</span>
        </div>
      );
    default:
      return null;
  }
}

function SubagentResultCard({
  ev,
  time,
  cardId,
  onTraceTo,
}: {
  ev: AgentEvent;
  time: string;
  cardId: string;
  onTraceTo: (id: string) => void;
}) {
  const id = ev.agent_id;
  const name = ev.payload.agent_name;
  // Only the two drafts cards carry double-click→fabric. The analysis
  // cards get the derivation viz instead (no navigation).
  const fabricLink =
    id === "alternate_outreach" || id === "program_manager_notifier"
      ? ev.fabric_link
      : null;
  return (
    <Card
      kind="subagent-done"
      time={time}
      agent={name}
      id={cardId}
      fabricLink={fabricLink}
    >
      <div className="agent-run-card-headline">✓ {name} complete</div>
      {id === "distribution_optimizer" && (
        <DistributionOptimizerBody ev={ev} onTraceTo={onTraceTo} />
      )}
      {id === "alternate_outreach" && (
        <div className="agent-run-card-body">
          <div>
            <strong>Primary outreach:</strong>{" "}
            {(ev.payload.primary as any[])
              .map((p: any) => p.name)
              .join(", ") || "(none — all alternates blocked)"}
          </div>
          {(ev.payload.blocked as any[]).length > 0 && (
            <div className="agent-run-card-note warn">
              ⚠ Blocked:{" "}
              {(ev.payload.blocked as any[])
                .map((b: any) => `${b.name} (${b.reason})`)
                .join("; ")}
            </div>
          )}
        </div>
      )}
      {id === "program_manager_notifier" && (
        <div className="agent-run-card-body">
          <strong>
            {(ev.payload.notifications as any[]).length} notification(s)
            drafted:
          </strong>
          <ul className="agent-run-card-list">
            {(ev.payload.notifications as any[]).map((n: any) => (
              <li key={n.program_id}>
                <code>{n.program_name}</code> → {n.to}
              </li>
            ))}
          </ul>
        </div>
      )}
      {id === "financial_summarizer" && (
        <FinancialSummarizerBody ev={ev} onTraceTo={onTraceTo} />
      )}
    </Card>
  );
}

// ---- Derivation visualisations -------------------------------------
// Both bodies render the analysis output PLUS a "Derivation" subsection
// that shows the math: which fabric inputs were combined, what the
// formula was, what the output number is. Ends with a "↗ Trace inputs"
// link that scrolls to + pulses the upstream programs_at_risk card.

function DistributionOptimizerBody({
  ev,
  onTraceTo,
}: {
  ev: AgentEvent;
  onTraceTo: (id: string) => void;
}) {
  const ranked = (ev.payload.ranked as any[]) || [];
  return (
    <div className="agent-run-card-body">
      <div className="agent-run-derivation-output">
        <strong>Allocation order:</strong>{" "}
        {ranked.map((r) => r.name).join(" → ")}
      </div>
      <div className="agent-run-card-note">{ev.payload.recommendation}</div>
      <div className="agent-run-derivation">
        <div className="agent-run-derivation-eyebrow">Derivation</div>
        <p className="agent-run-derivation-lead">
          Sorted the {ranked.length} Program nodes the fabric returned by
          revenue_at_risk_usd descending. Pure function of the fabric's
          program-impact walk — no external inputs.
        </p>
        <table className="agent-run-derivation-table">
          <thead>
            <tr>
              <th>Rank</th>
              <th>Program (fabric Program node)</th>
              <th>Revenue</th>
              <th>OTD/day</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((r, i) => (
              <tr key={r.program_id || i}>
                <td>{i + 1}</td>
                <td>{r.name}</td>
                <td>${r.revenue_usd_m}M</td>
                <td>${r.otd_penalty_usd_k_per_day}k</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button
          type="button"
          className="agent-run-derivation-trace"
          onClick={() => onTraceTo("agent-card-programs_at_risk_identified")}
        >
          ↗ Trace inputs back to the fabric subgraph response above
        </button>
      </div>
    </div>
  );
}

function FinancialSummarizerBody({
  ev,
  onTraceTo,
}: {
  ev: AgentEvent;
  onTraceTo: (id: string) => void;
}) {
  const breakdown = (ev.payload.breakdown as any[]) || [];
  return (
    <div className="agent-run-card-body">
      <div className="agent-run-derivation-output">
        <strong>${ev.payload.total_revenue_at_risk_usd_m}M</strong> revenue
        at risk · <strong>${ev.payload.total_otd_penalty_usd_k_per_day}k</strong>/day
        OTD penalty · worst-case{" "}
        <strong>${ev.payload.worst_case_penalty_usd_m}M</strong> over{" "}
        {ev.payload.days_to_mitigate_worst_case} days.
      </div>
      <div className="agent-run-derivation">
        <div className="agent-run-derivation-eyebrow">Derivation</div>
        <table className="agent-run-derivation-table">
          <thead>
            <tr>
              <th>Program (fabric Program node)</th>
              <th>Revenue</th>
              <th>OTD/day</th>
            </tr>
          </thead>
          <tbody>
            {breakdown.map((b) => (
              <tr key={b.program_id || b.name}>
                <td>{b.name}</td>
                <td>${b.revenue_usd_m}M</td>
                <td>${b.otd_penalty_usd_k_per_day}k</td>
              </tr>
            ))}
            <tr className="agent-run-derivation-total">
              <td>TOTAL (sum of fabric stakes)</td>
              <td>${ev.payload.total_revenue_at_risk_usd_m}M</td>
              <td>${ev.payload.total_otd_penalty_usd_k_per_day}k</td>
            </tr>
          </tbody>
        </table>
        <p className="agent-run-derivation-formula">
          Worst-case penalty = ${ev.payload.total_otd_penalty_usd_k_per_day}k/day
          × {ev.payload.days_to_mitigate_worst_case} days ÷ 1000 ={" "}
          <strong>${ev.payload.worst_case_penalty_usd_m}M</strong>
        </p>
        <button
          type="button"
          className="agent-run-derivation-trace"
          onClick={() => onTraceTo("agent-card-programs_at_risk_identified")}
        >
          ↗ Trace inputs back to the fabric subgraph response above
        </button>
      </div>
    </div>
  );
}

function Card({
  kind,
  time,
  agent,
  children,
  id,
  fabricLink,
}: {
  kind: string;
  time: string;
  agent: string;
  children: React.ReactNode;
  id?: string;
  fabricLink?: string | null;
}) {
  // Double-click anywhere on the card opens the fabric_link in a new
  // tab. Discoverable via the corner pill at the same time.
  const onDouble = fabricLink
    ? () => window.open(fabricLink, "_blank", "noreferrer")
    : undefined;
  return (
    <div
      id={id}
      className={
        `agent-run-card agent-run-card-${kind}` +
        (fabricLink ? " agent-run-card-clickable" : "")
      }
      onDoubleClick={onDouble}
      title={fabricLink ? "Double-click to open in the fabric" : undefined}
    >
      <div className="agent-run-card-meta">
        <span className="agent-run-card-agent">{agent}</span>
        <div className="agent-run-card-meta-right">
          {fabricLink && (
            <a
              href={fabricLink}
              target="_blank"
              rel="noreferrer"
              className="agent-run-card-corner-link"
              onClick={(e) => e.stopPropagation()}
            >
              ↗ Open in fabric
            </a>
          )}
          <span className="agent-run-card-time">{time}</span>
        </div>
      </div>
      {children}
    </div>
  );
}

function agentNameOf(ev: AgentEvent): string {
  // Best-effort label resolver — `agent_thinking` events don't always
  // carry agent_name; fall back to a humanised id.
  const known: Record<string, string> = {
    risk_monitor: "Risk Monitor",
    supplier_assurance: "Supplier Assurance Orchestrator",
    supplier_assurance_orchestrator: "Supplier Assurance Orchestrator",
    distribution_optimizer: "Distribution Optimizer",
    alternate_outreach: "Alternate Outreach",
    program_manager_notifier: "Program Manager Notifier",
    financial_summarizer: "Financial Impact Summarizer",
    financial_impact_summarizer: "Financial Impact Summarizer",
    orchestrator: "Orchestrator",
  };
  return known[ev.agent_id] || ev.payload?.agent_name || ev.agent_id;
}
