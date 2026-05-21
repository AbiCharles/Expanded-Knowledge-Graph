import { AuthUser } from "../auth";
import { CaseFull } from "../types";

interface Props {
  active: CaseFull | null;
  role: "operator" | "reviewer";
  user: AuthUser;
  onLogout: () => void;
  onOpenKnowledge: () => void;
  onOpenScenariosHelp: () => void;
  onOpenMetrics: () => void;
}

export function StatusBar({ active, role, user, onLogout, onOpenKnowledge, onOpenScenariosHelp, onOpenMetrics }: Props) {
  let stage = "Idle";
  if (active) {
    if (active.phase === "awaiting_clarification") stage = "Clarifying";
    else if (active.phase === "binding") stage = "Binding";
    else if (active.phase === "review_ready") stage = "Awaiting Review";
    else if (active.phase === "reviewing") stage = "Deciding";
    else if (active.phase === "complete") {
      if (active.decision_kind === "approve") stage = "Executed";
      else if (active.decision_kind === "reject") stage = "Aborted";
      else if (active.decision_kind === "request_more_info") stage = "Loop";
      else if (active.decision_kind === "auto_execute") stage = "Auto-executed";
    }
  }

  const operator = active?.scenario?.operator_role;
  const reviewer = active?.scenario?.reviewer_role;
  const pillRole = role === "reviewer" ? reviewer : operator;
  const ticketDisplay = active && active.lineage.find((l) => l.action === "submitted")?.detail || "—";

  return (
    <div className="statusbar">
      <div className="brand">
        <div className="brand-mark">TCS Knowledge Fabric</div>
      </div>

      <div className="status-meta">
        <div className="field">
          <div className="label">Case</div>
          <div className="value">{active ? active.case_id : "—"}</div>
        </div>
        <div className="field">
          <div className="label">Stage</div>
          <div className="value live">{stage}</div>
        </div>
        <div className="field">
          <div className="label">Transport</div>
          <div className="value">async</div>
        </div>
        <div className="field">
          <div className="label">Ticket</div>
          <div className="value dim">
            {(ticketDisplay && ticketDisplay.match(/async-[a-f0-9]+/)?.[0]) || "—"}
          </div>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center" }}>
        <button
          className="statusbar-action statusbar-action-quiet"
          onClick={onOpenMetrics}
          title="Live metrics dashboard"
        >
          Metrics
        </button>
        <button
          className="statusbar-action statusbar-action-quiet"
          onClick={onOpenScenariosHelp}
          title="How scenarios work"
        >
          Scenarios guide
        </button>
        <button className="statusbar-action" onClick={onOpenKnowledge}>
          Knowledge
        </button>
        <div className={`role-pill${role === "reviewer" ? " reviewer" : ""}`}>
          <div className="role-dot" />
          <div className="role-text">
            <div className="role-label">{pillRole?.label || "Operator"}</div>
            <div className="role-name">{pillRole?.name || user.display_name || user.username}</div>
          </div>
        </div>
        <button
          className="statusbar-action statusbar-action-quiet"
          onClick={onLogout}
          title={`Signed in as ${user.username} · click to log out`}
          style={{ marginLeft: 8, marginRight: 0 }}
        >
          {user.username} · log out
        </button>
      </div>
    </div>
  );
}
