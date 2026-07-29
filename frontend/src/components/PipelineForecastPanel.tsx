/**
 * Compact banner shown when a question is detected to span multiple scenarios.
 *
 * It's the always-visible entry point (the "chip"): it summarises the planned
 * pipeline + recommended pathway and opens the full-screen PipelineModal where
 * the reviewer approves one whole pathway. Approving executes it end-to-end;
 * the banner reflects live status. Owns the pipeline state + polling so the
 * modal is a pure view.
 */
import { useEffect, useRef, useState } from "react";

import * as api from "../api";
import { PipelineForecast, PipelineState } from "../types";
import { pct } from "./OutcomeTreeGraph";
import { PipelineModal } from "./PipelineModal";

export function PipelineForecastPanel({
  pipeline,
  onClose,
  onActiveCase,
}: {
  pipeline: PipelineForecast;
  onClose?: () => void;
  onActiveCase?: (caseId: string) => void;
}) {
  const [pstate, setPstate] = useState<PipelineState | null>(null);
  const [approving, setApproving] = useState(false);
  const [modalOpen, setModalOpen] = useState(true); // auto-open so it isn't missed
  const pollRef = useRef<number | undefined>(undefined);
  const lastActiveCase = useRef<string | null>(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = undefined;
    }
  };
  useEffect(() => stopPolling, []);

  const refresh = async () => {
    try {
      const p = await api.getPipeline(pipeline.pipeline_id);
      setPstate(p);
      const cur = p.steps[p.current_step];
      if (p.status === "running" && cur?.case_id && cur.case_id !== lastActiveCase.current) {
        lastActiveCase.current = cur.case_id;
        onActiveCase?.(cur.case_id);
      }
      if (p.status === "complete" || p.status === "error") {
        stopPolling();
        setApproving(false);
      }
      return p;
    } catch {
      return null;
    }
  };

  // New pipeline (new question) → reset + fetch its viable paths, auto-open.
  useEffect(() => {
    stopPolling();
    setPstate(null);
    setApproving(false);
    setModalOpen(true);
    lastActiveCase.current = null;
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pipeline.pipeline_id]);

  const approve = async (pathId: string) => {
    setApproving(true);
    try {
      await api.approvePath(pipeline.pipeline_id, pathId);
      await refresh();
      stopPolling();
      pollRef.current = window.setInterval(refresh, 1200);
    } catch (e) {
      setApproving(false);
      alert((e as Error).message);
    }
  };

  const status = pstate?.status ?? "planned";
  const paths = pstate?.viable_paths ?? [];
  const recommended = paths.find((p) => p.recommended);

  return (
    <section className="pipeline-banner" aria-label="Multi-scenario pipeline">
      <div className="pipeline-banner-main">
        <span className="pipeline-eyebrow">Multi-scenario question</span>
        <div className="pipeline-banner-row">
          <ol className="pipeline-steps compact">
            {pipeline.steps.map((s, i) => (
              <li key={`${s.scenario_id}-${i}`} title={s.why || s.scenario_id}>
                {i > 0 && <span className="pipeline-step-arrow">→</span>}
                <span className="pipeline-step-n">{i + 1}</span>
                <span className="pipeline-step-title">{s.title.split(" — ")[0]}</span>
              </li>
            ))}
          </ol>
          <div className="pipeline-banner-status">
            {status === "planned" && recommended && (
              <span className="pipeline-summary">
                {paths.length} viable pathways · recommended <strong>{recommended.label}</strong> ({pct(recommended.probability)})
              </span>
            )}
            {status === "running" && <span className="pipeline-status running">Executing pathway · step {(pstate?.current_step ?? 0) + 1}…</span>}
            {status === "complete" && <span className="pipeline-status complete">Pathway complete · ended on {pstate?.terminal_decision ?? "—"}</span>}
            {status === "error" && <span className="pipeline-status error">Error: {pstate?.error}</span>}
            <button className="pipeline-run" type="button" onClick={() => setModalOpen(true)}>
              View pathways ▸
            </button>
          </div>
        </div>
      </div>
      {onClose && (
        <button className="pipeline-close" type="button" onClick={onClose} aria-label="Dismiss">×</button>
      )}

      {modalOpen && (
        <PipelineModal
          pipeline={pipeline}
          pstate={pstate}
          onApprove={approve}
          approving={approving}
          onClose={() => setModalOpen(false)}
        />
      )}
    </section>
  );
}
