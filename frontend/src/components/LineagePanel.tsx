import { useEffect, useMemo, useState } from "react";
import { CaseFull, FactRow, LineageEvent, StagePayload } from "../types";
import { ActionSummary, compensateCase, listActions } from "../api";

type StripTab = "audit";

const TAB_LABELS: Record<StripTab, string> = {
  audit: "Audit trail",
};

// Right-edge tabbed strip. Collapsed it's a 44px white rail with two
// vertical tabs (Audit / Filters); clicking a tab expands the column to
// 360px showing that tab's body. Clicking the active tab again collapses
// it back to the strip. Active tab + open state are persisted to
// localStorage so a refresh keeps the reviewer's chosen view.
export function LineagePanel({
  active,
  onRefresh,
}: {
  active: CaseFull | null;
  onRefresh?: () => void;
}) {
  const [activeTab, setActiveTab] = useState<StripTab | null>(() => {
    if (typeof window === "undefined") return null;
    const open = localStorage.getItem("kf-lineage-open") === "1";
    if (!open) return null;
    const tab = localStorage.getItem("kf-lineage-tab") as StripTab | null;
    return tab && TAB_LABELS[tab] ? tab : "audit";
  });

  // One-shot fetch of the actions registry so we can look up
  // reversibility_class for any action that fired on this case. Used to
  // decide whether the "Compensate" button should appear next to an
  // executed event. Cached in component state — refetched only on mount.
  const [actionMeta, setActionMeta] = useState<Record<string, ActionSummary>>({});
  useEffect(() => {
    let cancelled = false;
    listActions().then((rows) => {
      if (cancelled) return;
      const m: Record<string, ActionSummary> = {};
      for (const r of rows) m[r.id] = r;
      setActionMeta(m);
    }).catch(() => { /* swallow — Compensate just won't appear */ });
    return () => { cancelled = true; };
  }, []);

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
          {activeTab === "audit" && (
            <AuditByStageView
              active={active}
              actionMeta={actionMeta}
              onRefresh={onRefresh}
            />
          )}
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
function AuditByStageView({
  active,
  actionMeta,
  onRefresh,
}: {
  active: CaseFull | null;
  actionMeta: Record<string, ActionSummary>;
  onRefresh?: () => void;
}) {
  const grouped = useMemo(() => groupByStage(active), [active]);
  // Pre-compute the compensation eligibility derived from the case +
  // actions registry. Shared by every StageBlock so we don't re-run the
  // logic per stage. The Compensate button appears on the executed
  // event when ALL of the following hold:
  //   • the case carries an `execution_result` with `ok=true`
  //   • the action's reversibility_class is "compensatable"
  //   • no `action.compensated` event has been emitted yet
  // After a successful compensate, the lineage gains an
  // `action.compensated` event which suppresses the button (one-shot).
  const compensation = useMemo((): {
    eligible: boolean;
    actionId: string | null;
    isCompensated: boolean;
    compensatedEvent?: LineageEvent;
    executedEvent?: LineageEvent;
  } => {
    if (!active) return { eligible: false, actionId: null, isCompensated: false };
    const er = active.execution_result;
    if (!er || !er.ok) return { eligible: false, actionId: null, isCompensated: false };
    const actionId = er.action_id;
    const meta = actionMeta[actionId];
    const compensatedEvent = active.lineage.find(
      (ev) =>
        ev.action === "action.compensated" ||
        ev.action === "action.compensate_failed",
    );
    const executedEvent = active.lineage.find((ev) => ev.action === "executed");
    return {
      eligible: !compensatedEvent && meta?.reversibility_class === "compensatable",
      actionId,
      isCompensated: !!compensatedEvent,
      compensatedEvent,
      executedEvent,
    };
  }, [active, actionMeta]);

  const [compensating, setCompensating] = useState(false);
  const handleCompensate = async () => {
    if (!active?.case_id || compensating) return;
    setCompensating(true);
    try {
      await compensateCase(active.case_id);
      onRefresh?.();
    } catch (err) {
      console.error("Compensate failed:", err);
    } finally {
      setCompensating(false);
    }
  };

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
          <StageBlock
            key={g.stage}
            stage={g}
            index={i + 1}
            compensation={compensation}
            onCompensate={handleCompensate}
            compensating={compensating}
          />
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

function StageBlock({
  stage,
  index,
  compensation,
  onCompensate,
  compensating,
}: {
  stage: GroupedStage;
  index: number;
  compensation: {
    eligible: boolean;
    actionId: string | null;
    isCompensated: boolean;
    compensatedEvent?: LineageEvent;
    executedEvent?: LineageEvent;
  };
  onCompensate: () => void;
  compensating: boolean;
}) {
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
        <details className="audit-stage-events" open>
          <summary className="audit-section-label">
            Raw events ({stage.events.length})
            <span className="audit-section-hint">click to collapse</span>
          </summary>
          <div className="audit-event-list">
            {stage.events.map((ev) => {
              const isExecuted = ev.action === "executed";
              const isCompensated = ev.action === "action.compensated";
              const isCompensateFailed = ev.action === "action.compensate_failed";
              const isAuthorityRecalc = ev.action === "authority.recalculated";
              return (
                <div
                  className={
                    `audit-event` +
                    (isExecuted ? " audit-event-executed" : "") +
                    (isCompensated ? " audit-event-compensated" : "") +
                    (isCompensateFailed ? " audit-event-compensate-failed" : "") +
                    (isAuthorityRecalc ? " audit-event-authority-recalculated" : "")
                  }
                  key={ev.sequence}
                >
                  <div className="audit-event-meta">
                    <span className="seq">#{String(ev.sequence).padStart(2, "0")}</span>
                    <span className="audit-event-action-name">{ev.action}</span>
                    <span>·</span>
                    <span>{ev.actor}</span>
                    {isCompensated &&
                      compensation.executedEvent &&
                      formatDelta(
                        compensation.executedEvent.timestamp,
                        ev.timestamp,
                      ) && (
                        <span className="audit-event-delta">
                          Compensated {formatDelta(
                            compensation.executedEvent.timestamp,
                            ev.timestamp,
                          )}{" "}later
                        </span>
                      )}
                  </div>
                  {ev.detail && <div className="audit-event-detail">{ev.detail}</div>}
                  {/* Compensate button — only on the original executed
                      event when the action is compensatable and hasn't
                      been compensated yet. */}
                  {isExecuted &&
                    compensation.eligible &&
                    !compensation.isCompensated && (
                      <div className="audit-event-actions">
                        <button
                          type="button"
                          className="audit-event-compensate-btn"
                          onClick={onCompensate}
                          disabled={compensating}
                          title={
                            `Fire the compensation executor for ` +
                            `${compensation.actionId ?? "this action"} — ` +
                            `records an action.compensated event on the ` +
                            `audit trail.`
                          }
                        >
                          {compensating ? "Compensating…" : "Compensate"}
                        </button>
                      </div>
                    )}
                </div>
              );
            })}
          </div>
        </details>
      )}
    </section>
  );
}

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------
// Render a short delta between two ISO timestamps, e.g. "0:34", "2 min",
// "1h 12m". Used on the audit.compensated event row to show how long
// after firing the action was rolled back. Returns null on parse failure
// so the caller can omit the badge.
function formatDelta(fromIso: string, toIso: string): string | null {
  try {
    const ms = new Date(toIso).getTime() - new Date(fromIso).getTime();
    if (!Number.isFinite(ms) || ms < 0) return null;
    const totalSec = Math.round(ms / 1000);
    if (totalSec < 60) return `${totalSec}s`;
    const min = Math.floor(totalSec / 60);
    const sec = totalSec % 60;
    if (min < 60) return `${min}m ${sec.toString().padStart(2, "0")}s`;
    const hr = Math.floor(min / 60);
    const restMin = min % 60;
    return `${hr}h ${restMin.toString().padStart(2, "0")}m`;
  } catch {
    return null;
  }
}

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
