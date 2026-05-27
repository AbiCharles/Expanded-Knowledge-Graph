import { useMemo, useState } from "react";
import { CaseFull, FactRow, LineageEvent, StagePayload } from "../types";

type StripTab = "audit";

const TAB_LABELS: Record<StripTab, string> = {
  audit: "Audit trail",
};

// Right-edge tabbed strip. Collapsed it's a 44px white rail with two
// vertical tabs (Audit / Filters); clicking a tab expands the column to
// 360px showing that tab's body. Clicking the active tab again collapses
// it back to the strip. Active tab + open state are persisted to
// localStorage so a refresh keeps the reviewer's chosen view.
export function LineagePanel({ active }: { active: CaseFull | null }) {
  const [activeTab, setActiveTab] = useState<StripTab | null>(() => {
    if (typeof window === "undefined") return null;
    const open = localStorage.getItem("kf-lineage-open") === "1";
    if (!open) return null;
    const tab = localStorage.getItem("kf-lineage-tab") as StripTab | null;
    return tab && TAB_LABELS[tab] ? tab : "audit";
  });

  const onTabClick = (tab: StripTab) => {
    const next = activeTab === tab ? null : tab;
    setActiveTab(next);
    try {
      localStorage.setItem("kf-lineage-open", next ? "1" : "0");
      if (next) localStorage.setItem("kf-lineage-tab", next);
    } catch { /* private mode */ }
  };

  const lineageCount = active?.lineage?.length ?? 0;

  return (
    <aside className={`lineage-panel${activeTab ? " lineage-open" : " lineage-collapsed"}`}>
      <nav className="lineage-strip" aria-label="Audit and graph controls">
        {(Object.keys(TAB_LABELS) as StripTab[]).map((tab) => (
          <button
            key={tab}
            type="button"
            className={`lineage-tab${activeTab === tab ? " active" : ""}`}
            onClick={() => onTabClick(tab)}
            aria-expanded={activeTab === tab}
            title={activeTab === tab ? "Click to collapse" : `Show ${TAB_LABELS[tab]}`}
          >
            {tab === "audit" && lineageCount > 0 && (
              <span className="lineage-tab-badge">{lineageCount}</span>
            )}
            <span className="lineage-tab-label">{TAB_LABELS[tab]}</span>
          </button>
        ))}
      </nav>
      {activeTab && (
        <div className="lineage-body" role="region" aria-label={TAB_LABELS[activeTab]}>
          {activeTab === "audit" && <AuditByStageView active={active} />}
        </div>
      )}
    </aside>
  );
}

// -----------------------------------------------------------------------------
// Audit tab — stage-by-stage view. Each stage shows its display name, the
// actor that ran it, the facts collected at that stage, and an expandable
// list of raw lineage events.
// -----------------------------------------------------------------------------
function AuditByStageView({ active }: { active: CaseFull | null }) {
  const grouped = useMemo(() => groupByStage(active), [active]);

  if (!active) {
    return (
      <>
        <header className="lineage-head">
          <div>
            <div className="lineage-eyebrow">Append-only audit log</div>
            <div className="lineage-title">Audit trail</div>
          </div>
        </header>
        <div className="lineage-feed">
          <div className="lineage-empty">Open a case to see its audit trail.</div>
        </div>
      </>
    );
  }

  return (
    <>
      <header className="lineage-head">
        <div>
          <div className="lineage-eyebrow">Append-only audit log · stage by stage</div>
          <div className="lineage-title">Audit trail
            {active.lineage.length > 0 && <span className="lineage-count">({active.lineage.length})</span>}
          </div>
        </div>
        <div className="lineage-live">Live</div>
      </header>
      <div className="lineage-feed">
        {grouped.length === 0 && <div className="lineage-empty">No stages yet.</div>}
        {grouped.map((g, i) => (
          <StageBlock key={g.stage} stage={g} index={i + 1} />
        ))}
      </div>
    </>
  );
}

interface GroupedStage {
  stage: string;
  facts: FactRow[];
  events: LineageEvent[];
  actor: string | null;
}

function StageBlock({ stage, index }: { stage: GroupedStage; index: number }) {
  return (
    <section className="audit-stage">
      <header className="audit-stage-head">
        <div className="audit-stage-name">
          Stage {index} · {stageDisplay(stage.stage)}
        </div>
        {stage.actor && <div className="audit-stage-actor">Agent · {stage.actor}</div>}
      </header>

      <div className="audit-stage-section">
        <div className="audit-section-label">Facts collected ({stage.facts.length})</div>
        {stage.facts.length === 0 ? (
          <div className="audit-section-empty">No facts at this stage.</div>
        ) : (
          <ul className="audit-fact-list">
            {stage.facts.map((f, idx) => (
              <li key={`${f.source}|${f.id}|${idx}`} className="audit-fact-row">
                <span className="audit-fact-type">{f.ontology_type}</span>
                <span className="audit-fact-id">{f.id}</span>
                {f.title && <span className="audit-fact-title">{f.title}</span>}
                <span className="audit-fact-source">{shortSource(f.source)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {stage.events.length > 0 && (
        <details className="audit-stage-events">
          <summary className="audit-section-label">
            Raw events ({stage.events.length})
            <span className="audit-section-hint">click to expand</span>
          </summary>
          <div className="audit-event-list">
            {stage.events.map((ev) => (
              <div className="audit-event" key={ev.sequence}>
                <div className="audit-event-meta">
                  <span className="seq">#{String(ev.sequence).padStart(2, "0")}</span>
                  <span>{ev.action}</span>
                  <span>·</span>
                  <span>{ev.actor}</span>
                </div>
                {ev.detail && <div className="audit-event-detail">{ev.detail}</div>}
              </div>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------
function groupByStage(active: CaseFull | null): GroupedStage[] {
  if (!active) return [];
  // Index lineage events by stage so we can attach them when we walk the
  // stages array (which has the facts).
  const eventsByStage = new Map<string, LineageEvent[]>();
  for (const ev of active.lineage || []) {
    if (!eventsByStage.has(ev.stage)) eventsByStage.set(ev.stage, []);
    eventsByStage.get(ev.stage)!.push(ev);
  }

  const out: GroupedStage[] = [];
  const seen = new Set<string>();

  // First, walk the official stages (which have facts).
  for (const s of active.stages || []) {
    out.push(buildGrouped(s.stage, s, eventsByStage));
    seen.add(s.stage);
  }

  // Then any stages that fired lineage events but have no facts payload
  // (intake, binding, complete, etc.) — append them in the order they
  // first appeared in the lineage.
  for (const ev of active.lineage || []) {
    if (!seen.has(ev.stage)) {
      out.push(buildGrouped(ev.stage, undefined, eventsByStage));
      seen.add(ev.stage);
    }
  }
  return out;
}

function buildGrouped(
  stage: string,
  payload: StagePayload | undefined,
  eventsByStage: Map<string, LineageEvent[]>,
): GroupedStage {
  const events = eventsByStage.get(stage) || [];
  // Actor heuristic: prefer the agent_intake / proposal / review actors.
  // Take the first non-system actor we see in this stage's events.
  const actor =
    events.find((ev) => ev.actor && !ev.actor.startsWith("system"))?.actor ??
    events[0]?.actor ??
    payload?.binder ??
    null;
  return {
    stage,
    facts: payload?.facts || [],
    events,
    actor,
  };
}

function stageDisplay(stage: string): string {
  switch (stage) {
    case "intake":             return "Intake";
    case "agent_intake":       return "Policy & scope";
    case "proposal":           return "Agent gathered";
    case "review":             return "For your decision";
    case "complete":           return "Complete";
    case "binding":            return "Binding";
    default:                   return stage;
  }
}

function shortSource(src: string | null | undefined): string {
  if (!src) return "";
  const k = src.includes(":") ? src.split(":", 1)[0] : src;
  return k;
}
