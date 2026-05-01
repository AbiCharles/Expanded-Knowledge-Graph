import { LineageEvent } from "../types";

export function LineagePanel({ lineage }: { lineage: LineageEvent[] }) {
  return (
    <aside className="lineage-panel">
      <div className="lineage-header">
        <div>
          <div className="lineage-eyebrow">Append-only audit log</div>
          <div className="lineage-title">Lineage</div>
        </div>
        <div className="lineage-live">Live</div>
      </div>
      <div className="lineage-feed">
        {lineage.length === 0 && <div className="lineage-empty">No events yet.</div>}
        {lineage.map((ev, i) => (
          <div className="lineage-event" key={ev.sequence} style={{ animationDelay: `${Math.min(i, 4) * 50}ms` }}>
            <div className="lineage-meta">
              <span className="seq">#{String(ev.sequence).padStart(2, "0")}</span>
              <span>{ev.stage}</span>
              <span>·</span>
              <span>{ev.action}</span>
            </div>
            <div className="lineage-actor">{ev.actor}</div>
            <div className="lineage-detail">{ev.detail}</div>
          </div>
        ))}
      </div>
    </aside>
  );
}
