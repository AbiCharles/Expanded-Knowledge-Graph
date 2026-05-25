import { useState } from "react";
import { LineageEvent } from "../types";

// Compliance-grade audit log. Useful for engineers and auditors; visual
// clutter for the operator running scenarios. Collapsed by default so the
// envelope keeps the operator's focus; remembered in localStorage.
export function LineagePanel({ lineage }: { lineage: LineageEvent[] }) {
  const [open, setOpen] = useState(() =>
    typeof window !== "undefined" && localStorage.getItem("kf-lineage-open") === "1"
  );
  const toggle = () => {
    const next = !open;
    setOpen(next);
    try { localStorage.setItem("kf-lineage-open", next ? "1" : "0"); } catch { /* private mode */ }
  };
  return (
    <aside className={`lineage-panel${open ? "" : " lineage-collapsed"}`}>
      <button
        type="button"
        className="lineage-header"
        onClick={toggle}
        aria-expanded={open}
        title="Click to show/hide the append-only audit log"
      >
        <div>
          <div className="lineage-eyebrow">Append-only audit log</div>
          <div className="lineage-title">
            <span className="lineage-chevron" aria-hidden="true">▸</span>
            Audit trail
            {lineage.length > 0 && (
              <span className="lineage-count">({lineage.length})</span>
            )}
          </div>
        </div>
        <div className="lineage-live">{open ? "Live" : "Show"}</div>
      </button>
      {open && (
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
      )}
    </aside>
  );
}
