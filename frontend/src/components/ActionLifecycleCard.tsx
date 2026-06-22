/**
 * Action lifecycle — the primary surface for Beat 4 of the deck.
 *
 * Renders a prominent card in the case envelope showing:
 *   • What action fired (action_id + title)
 *   • Whether it's compensatable, irreversible, or already compensated
 *   • A timeline (●━━━●) from "fired" to "reversed" (or "reversible")
 *   • The primary "Compensate" CTA when applicable
 *   • Plain-language explanation of WHY this matters — so the FDE doesn't
 *     need to verbalize Beat 4's framing; the card does it.
 *
 * Coexists with the buried Compensate button in LineagePanel (the audit
 * trail's raw-events row). Both call the same backend endpoint; the card
 * is the primary CTA, the LineagePanel button is the power-user fallback.
 */
import { useEffect, useState } from "react";
import { CaseFull } from "../types";
import { ActionSummary, compensateCase, listActions } from "../api";

interface Props {
  active: CaseFull | null;
  onRefresh?: () => void;
}

type LifecycleState =
  | "fired-compensatable"
  | "fired-compensated"
  | "fired-compensate-failed"
  | "fired-irreversible";

export function ActionLifecycleCard({ active, onRefresh }: Props) {
  const [actionMeta, setActionMeta] = useState<ActionSummary | null>(null);
  const [compensating, setCompensating] = useState(false);

  const er = active?.execution_result;
  const actionId = er?.action_id;

  // Fetch metadata for the one action that fired. Cached at component level
  // so a re-render doesn't re-fetch unnecessarily. Cleared when the active
  // case changes (or its action changes).
  useEffect(() => {
    if (!actionId) {
      setActionMeta(null);
      return;
    }
    let cancelled = false;
    listActions()
      .then((rows) => {
        if (cancelled) return;
        setActionMeta(rows.find((r) => r.id === actionId) ?? null);
      })
      .catch(() => {
        if (!cancelled) setActionMeta(null);
      });
    return () => {
      cancelled = true;
    };
  }, [actionId]);

  // Don't render when no action has fired (or when the framework hasn't
  // yet populated execution_result for this case).
  if (!er || !er.action_id || !er.ok) return null;

  const reversibility = actionMeta?.reversibility_class ?? "irreversible";

  const executedEvent = active?.lineage?.find((ev) => ev.action === "executed");
  const compensatedEvent = active?.lineage?.find(
    (ev) =>
      ev.action === "action.compensated" ||
      ev.action === "action.compensate_failed",
  );
  const compensationFailed = compensatedEvent?.action === "action.compensate_failed";
  const cr = active?.compensation_result;

  const state: LifecycleState = compensationFailed
    ? "fired-compensate-failed"
    : compensatedEvent
    ? "fired-compensated"
    : reversibility === "compensatable"
    ? "fired-compensatable"
    : "fired-irreversible";

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

  // Badge text reflects the live state — COMPENSATABLE before reversal,
  // REVERSED after, IRREVERSIBLE when the action can't be rolled back,
  // RECOVERY NEEDED when the reversal attempt itself failed.
  const badgeLabel: Record<LifecycleState, string> = {
    "fired-compensatable": "COMPENSATABLE",
    "fired-compensated": "REVERSED",
    "fired-compensate-failed": "RECOVERY NEEDED",
    "fired-irreversible": "IRREVERSIBLE",
  };

  return (
    <section className={`action-lifecycle action-lifecycle-${state}`}>
      <header className="action-lifecycle-head">
        <span className="action-lifecycle-eyebrow">Action lifecycle</span>
        <span className={`action-lifecycle-badge badge-${state}`}>
          {badgeLabel[state]}
        </span>
      </header>

      {/* Visual timeline — two dots + connector for compensatable/reversed
          states, a single dot for irreversible. Conveys "where in the
          lifecycle is this action right now" at a glance. */}
      <div className="action-lifecycle-timeline">
        <div className="lifecycle-node lifecycle-node-fired">
          <div className="lifecycle-dot lifecycle-dot-fired" />
          <div className="lifecycle-node-label">Fired</div>
          {executedEvent && (
            <div className="lifecycle-node-timestamp">
              {formatClock(executedEvent.timestamp)}
            </div>
          )}
        </div>

        {state !== "fired-irreversible" && (
          <div
            className={
              "lifecycle-connector " +
              (state === "fired-compensated" ? "connector-solid" : "")
            }
          >
            {state === "fired-compensated" && executedEvent && compensatedEvent && (
              <span className="lifecycle-connector-delta">
                Δ {formatDelta(executedEvent.timestamp, compensatedEvent.timestamp)}
              </span>
            )}
          </div>
        )}

        {state !== "fired-irreversible" && (
          <div
            className={
              "lifecycle-node " +
              (state === "fired-compensated"
                ? "lifecycle-node-reversed"
                : state === "fired-compensate-failed"
                ? "lifecycle-node-failed"
                : "lifecycle-node-pending")
            }
          >
            <div
              className={
                "lifecycle-dot " +
                (state === "fired-compensated"
                  ? "lifecycle-dot-reversed"
                  : state === "fired-compensate-failed"
                  ? "lifecycle-dot-failed"
                  : "lifecycle-dot-pending")
              }
            />
            <div className="lifecycle-node-label">
              {state === "fired-compensated"
                ? "Reversed"
                : state === "fired-compensate-failed"
                ? "Failed"
                : "Reversible"}
            </div>
            {compensatedEvent && (
              <div className="lifecycle-node-timestamp">
                {formatClock(compensatedEvent.timestamp)}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Action identification — id + human-readable title. Mono for the
          id so it reads as an audit-trail anchor (not prose). */}
      <div className="action-lifecycle-action">
        <code className="action-lifecycle-action-id">{er.action_id}</code>
        {actionMeta?.title && (
          <span className="action-lifecycle-action-title">{actionMeta.title}</span>
        )}
      </div>

      {/* Per-state result detail — what the fire (and compensation, if any)
          actually said. */}
      <div className="action-lifecycle-detail">
        <div className="action-lifecycle-detail-row">
          <span className="lifecycle-detail-eyebrow">Fire result</span>
          <span className="lifecycle-detail-text">{er.detail}</span>
        </div>
        {cr && (
          <div className="action-lifecycle-detail-row">
            <span
              className={
                "lifecycle-detail-eyebrow " +
                (cr.ok ? "" : "lifecycle-detail-eyebrow-failed")
              }
            >
              {cr.ok ? "Reversal result" : "Reversal FAILED"}
            </span>
            <span className="lifecycle-detail-text">{cr.detail}</span>
          </div>
        )}
      </div>

      {/* Primary CTA — only on the compensatable, not-yet-compensated state. */}
      {state === "fired-compensatable" && (
        <button
          type="button"
          className="action-lifecycle-cta"
          onClick={handleCompensate}
          disabled={compensating}
        >
          {compensating ? "Compensating…" : "Compensate · reverse this action"}
        </button>
      )}

      {/* Plain-language explainer — state-adaptive. Carries the Beat 4
          narrative so the FDE doesn't have to verbalize it. */}
      <div className="action-lifecycle-explainer">
        <span className="action-lifecycle-explainer-icon">
          {state === "fired-compensated"
            ? "✓"
            : state === "fired-compensate-failed" ||
              state === "fired-irreversible"
            ? "⚠"
            : "ⓘ"}
        </span>
        <span className="action-lifecycle-explainer-text">
          {state === "fired-compensatable" && (
            <>
              This action <strong>can be reversed cleanly</strong>. The
              rollback will land as its own audit event — the original fire
              remains attestable.
            </>
          )}
          {state === "fired-compensated" && (
            <>
              <strong>Rolled back without stranding the effect.</strong>{" "}
              Both the action AND its reversal are preserved on the audit
              trail.
            </>
          )}
          {state === "fired-compensate-failed" && (
            <>
              <strong>Compensation failed.</strong> The original action is
              still live in the external system; manual remediation may be
              required. The failed attempt is recorded on the audit trail.
            </>
          )}
          {state === "fired-irreversible" && (
            <>
              This action <strong>cannot be cleanly reversed</strong>. If
              circumstances change, remediation is a separate case, not a
              one-click rollback.
            </>
          )}
        </span>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// HH:MM:SS from an ISO timestamp. Used to anchor each timeline node to a
// specific clock moment without taking up much label space.
function formatClock(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "";
  }
}

// Short delta string ("4s" / "35s" / "1m 12s" / "2h 14m") between two ISO
// timestamps. Used on the timeline connector to show "how long after the
// fire was the action rolled back". Returns null on parse failure.
function formatDelta(from: string, to: string): string | null {
  try {
    const ms = new Date(to).getTime() - new Date(from).getTime();
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
