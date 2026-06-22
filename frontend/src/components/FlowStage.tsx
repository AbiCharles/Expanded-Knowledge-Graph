import { CaseFull, DecisionKind } from "../types";
import { Envelope } from "./Envelope";

interface Props {
  active: CaseFull | null;
  role: "operator" | "reviewer";
  onOpenReview: () => void;
  onRefresh?: () => void;
  onReplay?: (caseId: string, decision: DecisionKind) => void;
  onBaselineReplay?: (caseId: string) => void;
  onCompare?: (caseId: string) => void;
  baselineRunningForActive?: boolean;
}

const NODE_ORDER = ["agent", "propose", "review", "execute"] as const;
type NodeKey = (typeof NODE_ORDER)[number];

const NODE_LABELS: Record<NodeKey, { label: string; title: string; meta: string }> = {
  agent: { label: "Stage 1", title: "Agent", meta: "Reasons within scope" },
  propose: { label: "Stage 2", title: "Proposes Action", meta: "Drafts typed envelope" },
  review: { label: "Stage 3", title: "HITL Review", meta: "Human evidence package" },
  execute: { label: "Stage 4", title: "Outcome", meta: "Execute · Abort · Loop" },
};

export function FlowStage({
  active,
  role,
  onOpenReview,
  onRefresh,
  onReplay,
  onBaselineReplay,
  onCompare,
  baselineRunningForActive,
}: Props) {
  const position = stagePosition(active);
  const isAuto = !!active?.scenario?.autonomous;

  const subtitle = subtitleFor(active, role);
  const stepCounter = stepCounterFor(active, role);

  return (
    <main className={`flow-stage${role === "reviewer" ? " reviewer-mode" : ""}`}>
      <div className="flow-header">
        <div className={`flow-eyebrow${role === "reviewer" ? " reviewer" : ""}`}>
          <span>{role === "reviewer" ? "Reviewer view · TCS Knowledge Fabric" : "Live Demo · TCS Knowledge Fabric"}</span>
          {stepCounter && <span className="step-counter">{stepCounter}</span>}
        </div>
        <h1 className="flow-title">
          Knowledge flows through the <em>envelope</em>
        </h1>
        <p className="flow-sub" dangerouslySetInnerHTML={{ __html: subtitle }} />
      </div>

      <div className="nodes">
        {NODE_ORDER.map((key, idx) => {
          const cls = nodeClass(key, idx, position, active, isAuto);
          const status = nodeStatus(key, idx, position, active, isAuto);
          const onClick =
            key === "review" && active?.phase === "review_ready" ? onOpenReview : undefined;
          return (
            <div key={key} className={cls} data-node={key} onClick={onClick}>
              <div className="node-status">{status}</div>
              <div className="node-label">{NODE_LABELS[key].label}</div>
              <div className="node-title">{NODE_LABELS[key].title}</div>
              <div className="node-meta">{NODE_LABELS[key].meta}</div>
            </div>
          );
        })}
      </div>

      {active?.risk_band?.escalated && <AuthorityRecalculatedBanner active={active} />}

      {active && active.phase === "complete" && active.scenario && (
        <OutcomeBanner active={active} />
      )}

      <Envelope
        active={active}
        onRefresh={onRefresh}
        onReplay={onReplay}
        onBaselineReplay={onBaselineReplay}
        onCompare={onCompare}
        baselineRunningForActive={baselineRunningForActive}
      />
    </main>
  );
}

// =============================================================================
function stagePosition(active: CaseFull | null): number {
  if (!active) return 0;
  const stagesBound = active.stages.length;
  // Position is "how far the indicator has advanced": 0=idle, 1=intake bound, 2=proposal bound,
  // 3=review bound, 4=outcome
  if (active.phase === "complete") return 4;
  if (active.phase === "review_ready" || active.phase === "reviewing") return 3;
  return stagesBound;
}

function nodeClass(key: NodeKey, idx: number, pos: number, active: CaseFull | null, isAuto: boolean): string {
  const cls = ["node"];
  if (!active || pos === 0) cls.push("pending");
  else if (idx < pos - 1) cls.push("complete");
  else if (idx === pos - 1) cls.push("active");
  else cls.push("pending");

  if (key === "review" && active?.phase === "review_ready") {
    return "node awaiting-review";
  }
  if (key === "review" && active?.phase === "complete" && isAuto) {
    return "node auto-cleared";
  }
  if (key === "execute" && active?.phase === "complete" && isAuto) {
    return "node auto-executed";
  }
  return cls.join(" ");
}

function nodeStatus(key: NodeKey, idx: number, pos: number, active: CaseFull | null, isAuto: boolean): string {
  if (!active || pos === 0) return "Idle";
  if (key === "review" && active.phase === "review_ready") return "Awaiting";
  if (key === "review" && active.phase === "complete" && isAuto) return "Auto";
  if (key === "execute" && active.phase === "complete") {
    if (isAuto) return "Auto-executed";
    if (active.decision_kind === "approve") return "Executed";
    if (active.decision_kind === "reject") return "Aborted";
    if (active.decision_kind === "request_more_info") return "Looping";
  }
  if (idx < pos - 1) return "Bound";
  if (idx === pos - 1) return "Active";
  return "Idle";
}

function subtitleFor(active: CaseFull | null, role: "operator" | "reviewer"): string {
  if (!active)
    return "Send the agent a request from the left. Each stage binder attaches a slice of enterprise knowledge. The envelope grows. The reviewer sees everything. Lineage records every step.";
  const sc = active.scenario;
  const isAuto = sc?.autonomous;
  const id = `<strong>${sc?.id ?? active.scenario_id ?? ""}</strong> · ${sc?.domain ?? ""}`;

  if (active.phase === "awaiting_clarification") {
    return isAuto
      ? `${id} → Agent has interpreted the request and is confirming with the operator. No human review required.`
      : `${id} → Agent has interpreted the request and is asking the operator to confirm before proposing.`;
  }
  if (active.stages.length === 1) return `${id} → Agent intake binder has attached the active policy and the agent's scope.`;
  if (active.stages.length === 2)
    return isAuto
      ? `${id} → Proposal bound. Framework is evaluating whether HITL is required.`
      : `${id} → Proposal binder has attached the master-data references the action depends on.`;
  if (active.phase === "review_ready" && role === "operator")
    return `${id} → Review evidence assembled. The case is queued for the human reviewer.`;
  if (role === "reviewer")
    return `${id} → You're now the reviewer. The Teams card shows everything the framework bound across all stages. Make a decision.`;
  if (active.phase === "complete" && isAuto)
    return `${id} → Auto-approved by guardrail. The agent executed the action without human review.`;
  if (active.phase === "complete")
    return `${id} → Decision recorded. The agent has notified the operator. Lineage captures the full audit trail.`;
  return id;
}

function stepCounterFor(active: CaseFull | null, role: "operator" | "reviewer"): string {
  if (!active) return "";
  const isAuto = !!active.scenario?.autonomous;
  const total = isAuto ? 4 : 6;
  let n = 1;
  if (active.phase === "awaiting_clarification") n = 1;
  else if (active.stages.length === 1) n = 2;
  else if (active.stages.length === 2) n = 3;
  else if (active.phase === "review_ready" && role === "operator") n = 4;
  else if (role === "reviewer") n = 5;
  else if (active.phase === "complete") n = isAuto ? 4 : 6;
  return `Step ${n} of ${total}`;
}

// =============================================================================
// W4 / Beat 5 — banner that lands above the Envelope whenever the
// autonomy path was dynamically demoted by a matching risk_band. The
// original autonomy tier is struck through; the new tier is emphasised;
// the matched predicate + reason are surfaced so the reviewer can see
// AT A GLANCE why this case (and only this case) escalated.
function AuthorityRecalculatedBanner({ active }: { active: CaseFull }) {
  const rb = active.risk_band;
  if (!rb) return null;
  const opPretty: Record<string, string> = {
    gt: ">",
    gte: "≥",
    lt: "<",
    lte: "≤",
    eq: "=",
    ne: "≠",
  };
  const opSymbol = opPretty[rb.op ?? ""] ?? rb.op ?? "?";
  const matchedValue =
    typeof rb.matched_value === "number"
      ? rb.matched_value.toLocaleString()
      : String(rb.matched_value ?? "?");
  const threshold =
    typeof rb.threshold === "number"
      ? rb.threshold.toLocaleString()
      : String(rb.threshold ?? "?");
  return (
    <div className="authority-recalc-banner">
      <div className="authority-recalc-eyebrow">
        ⚖ Authority recalculated · band: {rb.band}
      </div>
      <div className="authority-recalc-ladder">
        <span className="authority-recalc-tier-orig">auto_execute</span>
        <span className="authority-recalc-arrow">→</span>
        <span className="authority-recalc-tier-new">review_ready</span>
      </div>
      <div className="authority-recalc-rule">
        <span className="authority-recalc-rule-label">Match</span>
        <code className="authority-recalc-rule-expr">
          {rb.matched_field} = {matchedValue} {opSymbol} {threshold}
        </code>
      </div>
      {rb.reason && (
        <p className="authority-recalc-reason">{rb.reason}</p>
      )}
    </div>
  );
}

function OutcomeBanner({ active }: { active: CaseFull }) {
  const decision = active.decision_kind;
  if (!decision || !active.scenario) return null;
  const outcome = active.scenario.outcomes[decision];
  if (!outcome) return null;
  const cls =
    decision === "approve"
      ? "outcome-approve"
      : decision === "reject"
      ? "outcome-reject"
      : decision === "auto_execute"
      ? "outcome-auto"
      : "outcome-info";
  const icon =
    decision === "approve"
      ? "✓"
      : decision === "reject"
      ? "✗"
      : decision === "auto_execute"
      ? "⚡"
      : "?";
  return (
    <div className={`outcome ${cls}`}>
      <div className="outcome-icon">{icon}</div>
      <div className="outcome-text">
        <div className="outcome-headline">{outcome.headline}</div>
        <div className="outcome-detail">{outcome.detail}</div>
      </div>
    </div>
  );
}
