import { useState } from "react";
import { CaseFull, StagePayload } from "../types";

const STAGE_LABEL: Record<string, string> = {
  agent_intake: "Agent intake",
  proposal: "Proposal",
  review: "Review",
};

export function Envelope({ active }: { active: CaseFull | null }) {
  const stages = active?.stages ?? [];
  const factCount = stages.reduce((acc, s) => acc + s.facts.length, 0);

  return (
    <div className="envelope-wrapper">
      <div className="envelope-eyebrow">
        <div className="envelope-title">The Knowledge Envelope</div>
        <div className="envelope-counter">
          <strong>{stages.length}</strong> stages bound · <strong>{factCount}</strong> facts attached
        </div>
      </div>
      <div className="envelope">
        {stages.length === 0 && <div className="envelope-empty">Awaiting first binding…</div>}
        {stages.map((s, idx) => (
          <StageBlock key={s.stage} stage={s} index={idx} />
        ))}
      </div>
    </div>
  );
}

function StageBlock({ stage, index }: { stage: StagePayload; index: number }) {
  // Each stage starts expanded (the user wants to see the work). Click the
  // header to collapse. Inside, the facts grid is capped with internal scroll
  // so a 30-fact port-disruption stage doesn't push the page below the fold.
  const [open, setOpen] = useState(true);
  return (
    <div className={`stage-block${open ? " stage-open" : " stage-collapsed"}`}>
      <button
        type="button"
        className="stage-header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <div className="stage-name">
          <span className="stage-chevron" aria-hidden="true">▸</span>
          Stage {index + 1} · {STAGE_LABEL[stage.stage] ?? stage.stage}
          <span className="stage-fact-count">({stage.facts.length})</span>
        </div>
        <div className="stage-binder">{stage.binder}</div>
      </button>
      {open && (
        <div className="facts-grid">
          {stage.facts.map((f, i) => (
            <div className="fact" key={`${f.source}-${f.id}`} style={{ animationDelay: `${i * 80}ms` }}>
              <div className="fact-source">
                [{f.source}] · {f.ontology_type}
              </div>
              <div className="fact-id">{f.title}</div>
              <div className="fact-payload">{f.summary}</div>
              {f.uri && (
                <a className="fact-uri" href="#" onClick={(e) => e.preventDefault()}>
                  → {f.uri}
                </a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
