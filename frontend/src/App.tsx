import { useCallback, useEffect, useState } from "react";
import * as api from "./api";
import { Console } from "./components/Console";
import { FlowStage } from "./components/FlowStage";
import { LineagePanel } from "./components/LineagePanel";
import { DataSourcesModal } from "./components/DataSourcesModal";
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
  | { kind: "datasources" };

export default function App() {
  const [scenarios, setScenarios] = useState<ScenarioRow[]>([]);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [active, setActive] = useState<CaseFull | null>(null);
  const [role, setRole] = useState<"operator" | "reviewer">("operator");
  const [modal, setModal] = useState<ModalState>({ kind: "none" });

  // -------------------------------------------------------------------------
  // Initial load
  // -------------------------------------------------------------------------
  useEffect(() => {
    api.listScenarios().then(setScenarios).catch(console.error);
    refreshCases();
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

  return (
    <>
      <StatusBar
        active={active}
        role={role}
        onOpenDataSources={() => setModal({ kind: "datasources" })}
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
      {modal.kind === "datasources" && (
        <DataSourcesModal
          onClose={() => setModal({ kind: "none" })}
          onScenariosChanged={() => api.listScenarios().then(setScenarios).catch(console.error)}
        />
      )}
    </>
  );
}
