import { useCallback, useEffect, useState } from "react";
import * as api from "./api";
import { AuthUser, clearAuth, fetchMe, getUser, logout as serverLogout } from "./auth";
import { Console } from "./components/Console";
import { LoginScreen } from "./components/LoginScreen";
import { FlowStage } from "./components/FlowStage";
import { LineagePanel } from "./components/LineagePanel";
import { KnowledgeModal, KnowledgeTab } from "./components/KnowledgeModal";
import { MetricsDashboard } from "./components/MetricsDashboard";
import { ScenarioEditModal } from "./components/ScenarioEditModal";
import { ScenariosHelp } from "./components/ScenariosHelp";
import {
  ApproveModal,
  AutoApproveModal,
  CompareModal,
  RationaleModal,
  TeamsCardModal,
} from "./components/Modals";
import { StatusBar } from "./components/StatusBar";
import { useCaseStream } from "./hooks/useCaseStream";
import { CaseFull, CaseSummary, DecisionKind, ScenarioRow } from "./types";

type ModalState =
  | { kind: "none" }
  | { kind: "teams" }
  | { kind: "approve" }
  | { kind: "rationale"; decision: "reject" | "request_more_info" }
  | { kind: "auto"; guardrailId: string; reason: string }
  | { kind: "compare"; cases: [CaseFull, CaseFull] }
  | { kind: "knowledge"; tab: KnowledgeTab }
  | { kind: "scenarios-help" }
  | { kind: "edit-scenario"; scenarioId: string }
  | { kind: "metrics" };

export default function App() {
  const [scenarios, setScenarios] = useState<ScenarioRow[]>([]);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [active, setActive] = useState<CaseFull | null>(null);
  const [role, setRole] = useState<"operator" | "reviewer">("operator");
  const [modal, setModal] = useState<ModalState>({ kind: "none" });
  const [user, setUser] = useState<AuthUser | null>(getUser());
  const [authChecked, setAuthChecked] = useState(false);

  // Validate the cached token on mount; expire it if the server says so.
  useEffect(() => {
    if (!user) {
      setAuthChecked(true);
      return;
    }
    fetchMe().then((u) => {
      if (!u) {
        clearAuth();
        setUser(null);
      } else {
        setUser(u);
      }
      setAuthChecked(true);
    });
  }, []);

  const onLogout = async () => {
    // Tell the server to blocklist the token (so a stolen copy can't be
    // reused). serverLogout() also clears localStorage.
    await serverLogout();
    setUser(null);
    setActiveId(null);
    setActive(null);
    setCases([]);
  };

  // When any API call returns 401, authedFetch clears the token and fires
  // this event; we drop the user back to the login screen.
  useEffect(() => {
    const handler = () => {
      setUser(null);
      setActiveId(null);
      setActive(null);
      setCases([]);
    };
    window.addEventListener("auth-expired", handler);
    return () => window.removeEventListener("auth-expired", handler);
  }, []);

  // -------------------------------------------------------------------------
  // Initial load
  // -------------------------------------------------------------------------
  useEffect(() => {
    api.listScenarios().then(setScenarios).catch(console.error);
    refreshCases();
  }, []);

  // The "Field reference →" link inside the Save form (which is two modals
  // deep) dispatches a window event we listen for here. Keeps the link from
  // having to thread a callback through 3 layers.
  useEffect(() => {
    const handler = () => setModal({ kind: "scenarios-help" });
    window.addEventListener("open-scenarios-help", handler);
    return () => window.removeEventListener("open-scenarios-help", handler);
  }, []);

  const refreshCases = useCallback(async () => {
    try {
      setCases(await api.listCases());
    } catch (e) {
      console.error(e);
    }
  }, []);

  const refreshActive = useCallback(async () => {
    if (!activeId) return;
    try {
      const full = await api.getCase(activeId);
      setActive(full);
    } catch (e) {
      console.error(e);
    }
  }, [activeId]);

  useEffect(() => {
    if (!activeId) {
      setActive(null);
      return;
    }
    refreshActive();
  }, [activeId, refreshActive]);

  // -------------------------------------------------------------------------
  // Live stream
  // -------------------------------------------------------------------------
  useCaseStream(activeId, {
    onStageBound: () => refreshActive(),
    onReviewReady: () => refreshActive(),
    onAutoApproved: (data) => {
      setModal({ kind: "auto", guardrailId: data.guardrail_id, reason: data.reason });
      refreshActive();
      refreshCases();
    },
    onDecided: () => {
      refreshActive();
      refreshCases();
      setRole("operator");
    },
  });

  // Whenever active goes to review_ready, allow the user to pop the Teams card
  // by clicking the Stage 3 node or the inline CTA. We don't auto-open it.

  // -------------------------------------------------------------------------
  // Actions
  // -------------------------------------------------------------------------
  const onSendPrompt = async (text: string) => {
    try {
      const result = await api.createCase(text);
      setActiveId(result.case_id);
      refreshCases();
    } catch (e) {
      console.error(e);
      alert((e as Error).message);
    }
  };

  const onConfirm = async () => {
    if (!active) return;
    await api.confirmCase(active.case_id);
    refreshActive();
    refreshCases();
  };

  const onPickCandidate = async (scenarioId: string) => {
    if (!active) return;
    await api.relinkCase(active.case_id, scenarioId);
    refreshActive();
    refreshCases();
  };

  const onDeleteCase = async (caseId: string) => {
    await api.deleteCase(caseId);
    if (activeId === caseId) setActiveId(null);
    refreshCases();
  };

  const onClearCompleted = async () => {
    await api.clearCases("complete");
    refreshCases();
  };
  const onCancel = async () => {
    if (!active) return;
    await api.cancelCase(active.case_id);
    refreshActive();
    refreshCases();
  };

  const onOpenReview = () => {
    if (active?.phase === "review_ready") {
      setRole("reviewer");
      setModal({ kind: "teams" });
    }
  };

  const onTeamsDecision = (d: DecisionKind) => {
    if (d === "approve") setModal({ kind: "approve" });
    else setModal({ kind: "rationale", decision: d });
  };

  const onApproveConfirm = async () => {
    if (!active) return;
    const ticket = active.lineage.find((l) => l.action === "submitted")?.detail?.match(/async-[a-f0-9]+/)?.[0];
    if (!ticket) return;
    await api.postDecision(ticket, {
      decision: "approve",
      reviewer_id: active.scenario?.reviewer_role?.name || "reviewer",
      rationale: "",
    });
    setModal({ kind: "none" });
  };

  const onRationaleSubmit = async (rationale: string, followUp: string | null) => {
    if (!active || modal.kind !== "rationale") return;
    const ticket = active.lineage.find((l) => l.action === "submitted")?.detail?.match(/async-[a-f0-9]+/)?.[0];
    if (!ticket) return;
    await api.postDecision(ticket, {
      decision: modal.decision,
      reviewer_id: active.scenario?.reviewer_role?.name || "reviewer",
      rationale,
      follow_up: followUp,
    });
    setModal({ kind: "none" });
  };

  const onReplay = async (caseId: string, decision: DecisionKind) => {
    const result = await api.replayCase(caseId, decision);
    setActiveId(result.case_id);
    refreshCases();
  };

  const onCompare = async (caseId: string) => {
    const c = cases.find((x) => x.case_id === caseId);
    if (!c) return;
    const sibling = c.sibling_case_ids.find((sid) => {
      const s = cases.find((cs) => cs.case_id === sid);
      return s && s.phase === "complete";
    });
    if (!sibling) return;
    const [aFull, bFull] = await Promise.all([api.getCase(c.case_id), api.getCase(sibling)]);
    setModal({ kind: "compare", cases: [aFull, bFull] });
  };

  // -------------------------------------------------------------------------
  // Lock composer while a case is mid-flight
  // -------------------------------------------------------------------------
  const composerLocked =
    !!active &&
    (active.phase === "awaiting_clarification" ||
      active.phase === "binding" ||
      active.phase === "review_ready" ||
      active.phase === "reviewing");

  if (!authChecked) {
    return <div className="login-shell"><div className="login-card">Loading…</div></div>;
  }
  if (!user) {
    return <LoginScreen onAuth={(u) => setUser(u)} />;
  }

  return (
    <>
      <StatusBar
        active={active}
        role={role}
        user={user}
        onLogout={onLogout}
        onOpenKnowledge={() => setModal({ kind: "knowledge", tab: "sources" })}
        onOpenScenariosHelp={() => setModal({ kind: "scenarios-help" })}
        onOpenMetrics={() => setModal({ kind: "metrics" })}
      />
      <div className="main">
        <Console
          scenarios={scenarios}
          cases={cases}
          active={active}
          role={role}
          composerLocked={composerLocked}
          onSendPrompt={onSendPrompt}
          onConfirm={onConfirm}
          onCancel={onCancel}
          onSelectCase={setActiveId}
          onReplay={onReplay}
          onCompare={onCompare}
          onOpenReview={onOpenReview}
          onPickCandidate={onPickCandidate}
          onDeleteCase={onDeleteCase}
          onClearCompleted={onClearCompleted}
          onEditScenario={(sid) => setModal({ kind: "edit-scenario", scenarioId: sid })}
        />
        <FlowStage active={active} role={role} onOpenReview={onOpenReview} />
        <LineagePanel lineage={active?.lineage ?? []} />
      </div>

      {modal.kind === "teams" && active?.scenario && (
        <TeamsCardModal active={active} onClose={() => { setModal({ kind: "none" }); setRole("operator"); }} onDecision={onTeamsDecision} />
      )}
      {modal.kind === "rationale" && active && (
        <RationaleModal active={active} decision={modal.decision} onClose={() => setModal({ kind: "teams" })} onSubmit={onRationaleSubmit} />
      )}
      {modal.kind === "approve" && active && (
        <ApproveModal active={active} onCancel={() => setModal({ kind: "teams" })} onConfirm={onApproveConfirm} />
      )}
      {modal.kind === "auto" && (
        <AutoApproveModal guardrailId={modal.guardrailId} reason={modal.reason} onClose={() => setModal({ kind: "none" })} />
      )}
      {modal.kind === "compare" && (
        <CompareModal cases={modal.cases} onClose={() => setModal({ kind: "none" })} />
      )}
      {modal.kind === "knowledge" && (
        <KnowledgeModal
          initialTab={modal.tab}
          onClose={() => setModal({ kind: "none" })}
          onScenariosChanged={() => api.listScenarios().then(setScenarios).catch(console.error)}
        />
      )}
      {modal.kind === "scenarios-help" && (
        <ScenariosHelp onClose={() => setModal({ kind: "none" })} />
      )}
      {modal.kind === "edit-scenario" && (
        <ScenarioEditModal
          scenarioId={modal.scenarioId}
          onClose={() => setModal({ kind: "none" })}
          onSaved={() => api.listScenarios().then(setScenarios).catch(console.error)}
        />
      )}
      {modal.kind === "metrics" && (
        <MetricsDashboard onClose={() => setModal({ kind: "none" })} />
      )}
    </>
  );
}
