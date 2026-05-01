// Subscribes to /api/cases/:id/events using EventSource.
// Each event kind is dispatched to a separate handler; the hook closes the
// connection when the case completes ("done" event) or unmounts.

import { useEffect } from "react";

export type CaseStreamHandlers = {
  onStageBound?: (data: any) => void;
  onReviewReady?: (data: any) => void;
  onDecided?: (data: any) => void;
  onAutoApproved?: (data: any) => void;
  onCancelled?: (data: any) => void;
};

export function useCaseStream(caseId: string | null, handlers: CaseStreamHandlers) {
  useEffect(() => {
    if (!caseId) return;
    const url = `/api/cases/${caseId}/events`;
    const src = new EventSource(url);

    const dispatch = (kind: keyof CaseStreamHandlers, data: any) => {
      const fn = handlers[kind];
      if (fn) fn(data);
    };

    src.addEventListener("stage_bound", (e) => dispatch("onStageBound", JSON.parse((e as MessageEvent).data)));
    src.addEventListener("review_ready", (e) => dispatch("onReviewReady", JSON.parse((e as MessageEvent).data)));
    src.addEventListener("decided", (e) => dispatch("onDecided", JSON.parse((e as MessageEvent).data)));
    src.addEventListener("auto_approved", (e) => dispatch("onAutoApproved", JSON.parse((e as MessageEvent).data)));
    src.addEventListener("cancelled", (e) => dispatch("onCancelled", JSON.parse((e as MessageEvent).data)));
    src.addEventListener("done", () => src.close());

    src.onerror = () => {
      // Server closes the stream when the case completes; treat as normal.
      src.close();
    };

    return () => src.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId]);
}
