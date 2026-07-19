// Post-confirm "agents are working" modal. Shown from the moment the operator
// clicks "yes, proceed" until the autonomous run settles, then auto-closes to
// reveal the finished evidence view.
//
// The step list is derived entirely from the case's real state (phase, bound
// stages, lineage actions) — never a fixed timer — so it can't get ahead of the
// backend. Because those snapshots arrive batchy (the proposal bind carries the
// synthesis in one shot), a small reveal stagger ticks the completed steps in
// one at a time so it reads as agents working rather than a single jump.

import { useEffect, useMemo, useState } from "react";
import { CaseFull } from "../types";

type StepStatus = "done" | "active" | "pending";

interface WorkStep {
  key: string;
  label: string;
  detail: string;
  done: boolean;
}

function computeSteps(active: CaseFull | null): WorkStep[] {
  const stageIds = new Set((active?.stages || []).map((s) => s.stage));
  const actions = (active?.lineage || []).map((l) => l.action);
  const hasStage = (id: string) => stageIds.has(id);
  const hasSynthesis = actions.some((a) => a.startsWith("synthesis."));
  const hasExecuted = actions.some(
    (a) => a === "executed" || a === "auto-approved",
  );
  const phase = active?.phase;
  const isComplete = phase === "complete";
  return [
    {
      key: "interpret",
      label: "Interpreting the request",
      detail: "Classifying to a governed scenario",
      done: !!active,
    },
    {
      key: "context",
      label: "Binding governed context",
      detail: "Policy, reviewer scope & the failure report",
      done: hasStage("agent_intake"),
    },
    {
      key: "evidence",
      label: "Gathering evidence",
      detail: "C-scan vision · telemetry · evidence graph · prior NCRs",
      done: hasStage("proposal"),
    },
    {
      key: "analyses",
      label: "Running root-cause analyses",
      detail: "5-Why · Ishikawa · Pareto · evidence graph",
      done: hasSynthesis || hasStage("review") || isComplete,
    },
    {
      key: "capa",
      label: "Issuing the corrective action",
      detail: "Drafting & committing the CAPA",
      done: hasExecuted || isComplete,
    },
    {
      key: "done",
      label: "Investigation complete",
      detail: "Assembling the full evidence package",
      done: isComplete,
    },
  ];
}

export function WorkingModal({
  active,
  onClose,
}: {
  active: CaseFull | null;
  onClose: () => void;
}) {
  const steps = useMemo(() => computeSteps(active), [active]);
  const target = steps.filter((s) => s.done).length;

  const phase = active?.phase;
  // review_ready is terminal for this modal too: a HITL scenario has finished
  // the agent work and is now waiting on a human, so we close and hand off.
  const isTerminal =
    phase === "complete" || phase === "review_ready" || phase === "cancelled";

  // Reveal completed steps one at a time so batchy backend snapshots still read
  // as agents ticking through the work.
  const [revealed, setRevealed] = useState(1);
  useEffect(() => {
    if (revealed >= target) return;
    const t = window.setTimeout(() => setRevealed((n) => n + 1), 650);
    return () => window.clearTimeout(t);
  }, [revealed, target]);

  // Auto-close once every available step has been revealed AND the run settled.
  useEffect(() => {
    if (isTerminal && revealed >= target) {
      const t = window.setTimeout(onClose, 1200);
      return () => window.clearTimeout(t);
    }
    return undefined;
  }, [isTerminal, revealed, target, onClose]);

  // Safety net — never pin the UI even if step accounting ever drifts.
  useEffect(() => {
    if (!isTerminal) return undefined;
    const t = window.setTimeout(onClose, 9000);
    return () => window.clearTimeout(t);
  }, [isTerminal, onClose]);

  const allDone = isTerminal && revealed >= steps.length;
  const activeIndex = allDone ? -1 : Math.min(revealed, steps.length - 1);

  return (
    <div className="working-modal-backdrop">
      <div
        className="working-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Agents working"
      >
        <div className="working-modal-head">
          <div className="working-modal-eyebrow">
            {allDone ? (
              "Investigation complete"
            ) : (
              <>
                <span className="working-step-spinner small" /> Agents are working
              </>
            )}
          </div>
          <h2 className="working-modal-title">
            {active?.scenario?.title || "Running the investigation"}
          </h2>
          <p className="working-modal-sub">
            {allDone
              ? "Evidence bound, analyses run, action issued — opening the full evidence package…"
              : "The agents are binding evidence and reasoning to a root cause. This runs autonomously — you'll land on the full, auditable evidence package."}
          </p>
        </div>
        <ol className="working-steps">
          {steps.map((s, i) => {
            const status: StepStatus =
              i < revealed && s.done
                ? "done"
                : i === activeIndex
                  ? "active"
                  : "pending";
            return (
              <li key={s.key} className={`working-step ${status}`}>
                <span className="working-step-icon" aria-hidden="true">
                  {status === "done" ? (
                    "✓"
                  ) : status === "active" ? (
                    <span className="working-step-spinner" />
                  ) : (
                    <span className="working-step-dot" />
                  )}
                </span>
                <span className="working-step-body">
                  <span className="working-step-label">{s.label}</span>
                  <span className="working-step-detail">{s.detail}</span>
                </span>
              </li>
            );
          })}
        </ol>
        <div className="working-modal-foot">
          {allDone ? (
            <button
              type="button"
              className="working-modal-btn"
              onClick={onClose}
            >
              View results
            </button>
          ) : (
            <span className="working-modal-hint">
              Please wait — this usually takes a few seconds.
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
