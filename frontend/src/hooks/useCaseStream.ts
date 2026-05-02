// Subscribes to /api/cases/:id/events using EventSource.
// Each event kind is dispatched to a separate handler; the hook closes the
// connection when the case completes ("done" event) or unmounts.
//
// Auto-reconnects on transient network errors with exponential backoff,
// capped at 30s. Reviews can sit open for hours, so the connection has to
// survive idle network blips. We stop reconnecting once we've seen `done`
// (case complete) or the component unmounts.

import { useEffect, useRef } from "react";

export type CaseStreamHandlers = {
  onStageBound?: (data: any) => void;
  onReviewReady?: (data: any) => void;
  onDecided?: (data: any) => void;
  onAutoApproved?: (data: any) => void;
  onCancelled?: (data: any) => void;
};

export function useCaseStream(caseId: string | null, handlers: CaseStreamHandlers) {
  // Stash handlers in a ref so reconnects don't re-trigger when handlers
  // change (which they do on every parent render).
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    if (!caseId) return;
    let stopped = false;
    let attempt = 0;
    let currentSource: EventSource | null = null;
    let reconnectTimer: number | null = null;

    const dispatch = (kind: keyof CaseStreamHandlers, data: any) => {
      const fn = handlersRef.current[kind];
      if (fn) fn(data);
    };

    const connect = () => {
      if (stopped) return;
      const src = new EventSource(`/api/cases/${caseId}/events`);
      currentSource = src;

      src.addEventListener("stage_bound", (e) => dispatch("onStageBound", JSON.parse((e as MessageEvent).data)));
      src.addEventListener("review_ready", (e) => dispatch("onReviewReady", JSON.parse((e as MessageEvent).data)));
      src.addEventListener("decided", (e) => dispatch("onDecided", JSON.parse((e as MessageEvent).data)));
      src.addEventListener("auto_approved", (e) => dispatch("onAutoApproved", JSON.parse((e as MessageEvent).data)));
      src.addEventListener("cancelled", (e) => dispatch("onCancelled", JSON.parse((e as MessageEvent).data)));
      src.addEventListener("done", () => {
        // Server signals end-of-stream; don't reconnect.
        stopped = true;
        src.close();
      });

      src.onopen = () => {
        // Reset backoff on successful open
        attempt = 0;
      };

      src.onerror = () => {
        // EventSource reports `error` for both transient network blips and
        // server-closed streams. Re-open with exponential backoff up to 30s.
        if (stopped) return;
        src.close();
        currentSource = null;
        const delay = Math.min(30_000, 500 * Math.pow(2, attempt));
        attempt += 1;
        reconnectTimer = window.setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      stopped = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      if (currentSource) currentSource.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId]);
}
