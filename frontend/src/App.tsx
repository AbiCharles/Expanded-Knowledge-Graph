import { useCallback, useEffect, useState } from "react";
import * as api from "./api";
import { AuthUser, clearAuth, fetchMe, getUser, logout as serverLogout } from "./auth";
import { Console } from "./components/Console";
import { LoginScreen } from "./components/LoginScreen";
import { FlowStage } from "./components/FlowStage";
import { PlatformFlowModal } from "./components/GraphViz";
import { CaseSpecModal } from "./components/CaseSpecModal";
import { LineagePanel } from "./components/LineagePanel";
import { KnowledgeModal, KnowledgeTab } from "./components/KnowledgeModal";
import { InsightsModal } from "./components/InsightsModal";
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
import { AgentRun } from "./components/AgentRun";
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
  | { kind: "metrics" }
  | { kind: "insights" }
  | { kind: "platform-flow" }
  | { kind: "case-spec"; tab?: "scenario" | "ontology"; anchor?: string };

export default function App() {
  const [scenarios, setScenarios] = useState<ScenarioRow[]>([]);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [active, setActive] = useState<CaseFull | null>(null);
  const [role, setRole] = useState<"operator" | "reviewer">("operator");
  const [modal, setModal] = useState<ModalState>({ kind: "none" });
  // W8 — agent-run view (companion service). When true, the
  // top-level layout swaps the fabric chrome for the AgentRun
  // timeline component. Driven by the StatusBar "Agent run" button.
  const [agentRunOpen, setAgentRunOpen] = useState<boolean>(
    () => typeof window !== "undefined" && window.location.pathname === "/agent-run",
  );
  // W5 / Beat 2 — when a baseline replay is in flight, the case id of the
  // ORIGINAL case that triggered it. CounterfactualCard reads this to
  // render a "Running baseline..." state on the matching case.
  const [baselineRunning, setBaselineRunning] = useState<string | null>(null);
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

  // W8 — deep-link from the agent-orchestrator companion app.
  // URL shape: ?launch=aeronova&view=graph|pathways|stages
  // Two-stage handoff:
  //   1. On mount, read the URL params and stash them in React state.
  //      Don't fire anything yet — the user might not be logged in.
  //   2. Once `user` is set, fire createCase + confirmCase. The
  //      view-opener (further down) watches `active.stages` and pops
  //      the right modal once the case has bound.
  const [pendingLaunch, setPendingLaunch] = useState<{
    prompt: string;
    view: string | null;
  } | null>(null);
  const [pendingView, setPendingView] = useState<string | null>(null);
  const [launchedOnce, setLaunchedOnce] = useState(false);
  // Visible status banner during auto-launch so the audience can see
  // the chain of steps (and so we can debug failures without DevTools).
  const [launchStatus, setLaunchStatus] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("launch") === "aeronova") {
      setPendingLaunch({
        prompt: params.get("prompt") || "",
        view: params.get("view"),
      });
      setLaunchStatus("Detected agent-run deep-link · waiting for auth…");
      // Strip the params so a reload doesn't keep re-firing the launch.
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, []);

  // Fire the auto-launch once both the URL params AND the user are
  // available. Only runs once per session (guarded by launchedOnce).
  useEffect(() => {
    if (!pendingLaunch || !user || launchedOnce) return;
    if (pendingLaunch.view) setPendingView(pendingLaunch.view);
    setLaunchedOnce(true);
    const { prompt } = pendingLaunch;
    if (!prompt) {
      setPendingLaunch(null);
      setLaunchStatus(null);
      return;
    }
    setLaunchStatus("Auto-launching Aeronova case from the agent run…");
    api
      .createCase(prompt)
      .then((res) => {
        setLaunchStatus(`Case ${res.case_id} created · confirming…`);
        setActiveId(res.case_id);
        refreshCases();
        return api.confirmCase(res.case_id);
      })
      .then(() => {
        setLaunchStatus("Case confirmed · waiting for stages to bind…");
        return refreshActive();
      })
      .catch((e) => {
        console.warn("auto-launch failed:", e);
        setLaunchStatus(`Auto-launch failed: ${(e as Error).message}`);
      })
      .finally(() => setPendingLaunch(null));
  }, [pendingLaunch, user, launchedOnce]);

  // Clear the launch status banner once the modal opens (or after 8s
  // failsafe).
  useEffect(() => {
    if (!launchStatus) return;
    if (!launchedOnce) return;
    const t = setTimeout(() => setLaunchStatus(null), 8000);
    return () => clearTimeout(t);
  }, [launchStatus, launchedOnce]);

  // Counter signals plumbed down through FlowStage → Envelope →
  // GraphPanel. When bumped, GraphPanel auto-opens its modal on the
  // requested tab. Counters > window events because the value lives
  // in React state — GraphPanel reads the latest value on every
  // render, so even if it mounts AFTER the bump, the modal opens.
  const [networkOpenCounter, setNetworkOpenCounter] = useState(0);
  const [pathwaysOpenCounter, setPathwaysOpenCounter] = useState(0);

  // Fire the requested view once the active case has stage facts to
  // render against. Bumps the right counter; the signal propagates
  // down to GraphPanel which opens its modal at the requested tab.
  // We bump TWICE — once immediately and once on a 700ms timer — to
  // guard against the case where GraphPanel hasn't fully mounted yet
  // when the first bump lands. Each bump is a fresh counter value,
  // so React will re-trigger GraphPanel's useEffect either way.
  useEffect(() => {
    if (!pendingView) return;
    if (!active || (active.stages?.length ?? 0) === 0) return;
    if (pendingView === "stages") {
      setTimeout(() => {
        const el = document.querySelector(".envelope");
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 200);
    } else if (pendingView === "pathways") {
      setPathwaysOpenCounter((n) => n + 1);
      setTimeout(() => setPathwaysOpenCounter((n) => n + 1), 700);
      setLaunchStatus("✓ Opening knowledge graph · Decision pathways tab");
    } else if (pendingView === "graph") {
      setNetworkOpenCounter((n) => n + 1);
      setTimeout(() => setNetworkOpenCounter((n) => n + 1), 700);
      setLaunchStatus("✓ Opening knowledge graph · Network tab");
    }
    setPendingView(null);
  }, [pendingView, active]);

  // The graph-modal side-legend ⓘ buttons and the platform-flow
  // Scenario-node tap both dispatch this window event so they can pop
  // the Case-spec modal without threading a callback through Cytoscape.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail || {};
      setModal({ kind: "case-spec", tab: detail.tab, anchor: detail.anchor });
    };
    window.addEventListener("open-case-spec", handler as EventListener);
    return () => window.removeEventListener("open-case-spec", handler as EventListener);
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
  // Spans the network round-trip on createCase (LLM classifier ~1-3s) and
  // confirmCase (orchestrator start). Drives the "agent is thinking" indicator
  // in the Console so the user gets feedback BEFORE the case's own `binding`
  // phase event arrives via SSE.
  const [isSubmitting, setIsSubmitting] = useState(false);

  const onSendPrompt = async (text: string) => {
    setIsSubmitting(true);
    try {
      const result = await api.createCase(text);
      setActiveId(result.case_id);
      refreshCases();
    } catch (e) {
      console.error(e);
      alert((e as Error).message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const onConfirm = async () => {
    if (!active) return;
    setIsSubmitting(true);
    try {
      await api.confirmCase(active.case_id);
      refreshActive();
      refreshCases();
    } finally {
      setIsSubmitting(false);
    }
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

  const onApproveConfirm = async (highlightedRefs: api.HighlightedFactRef[]) => {
    if (!active) return;
    const ticket = active.lineage.find((l) => l.action === "submitted")?.detail?.match(/async-[a-f0-9]+/)?.[0];
    if (!ticket) return;
    await api.postDecision(ticket, {
      decision: "approve",
      reviewer_id: active.scenario?.reviewer_role?.name || "reviewer",
      rationale: "",
      highlighted_fact_refs: highlightedRefs,
    });
    setModal({ kind: "none" });
  };

  const onRationaleSubmit = async (
    rationale: string,
    followUp: string | null,
    highlightedRefs: api.HighlightedFactRef[],
  ) => {
    if (!active || modal.kind !== "rationale") return;
    const ticket = active.lineage.find((l) => l.action === "submitted")?.detail?.match(/async-[a-f0-9]+/)?.[0];
    if (!ticket) return;
    await api.postDecision(ticket, {
      decision: modal.decision,
      reviewer_id: active.scenario?.reviewer_role?.name || "reviewer",
      rationale,
      follow_up: followUp,
      highlighted_fact_refs: highlightedRefs,
    });
    setModal({ kind: "none" });
  };

  const onReplay = async (caseId: string, decision: DecisionKind) => {
    const result = await api.replayCase(caseId, decision);
    setActiveId(result.case_id);
    refreshCases();
  };

  // W5 / Beat 2 — kick off a baseline replay AND keep the user on the
  // original case (so they can immediately compare). Polls the new case
  // until phase === "complete" then auto-opens the CompareModal between
  // the original and the new baseline sibling. One-click demo flow.
  const onBaselineReplay = async (caseId: string) => {
    if (baselineRunning) return; // already one running for some case
    setBaselineRunning(caseId);
    try {
      const result = await api.replayCase(caseId, null, { baseline: true });
      refreshCases();
      const newBaselineId = result.case_id;
      const startTime = Date.now();
      const TIMEOUT_MS = 30_000;
      const POLL_INTERVAL_MS = 500;

      const tryComplete = async () => {
        // Time-out safety so a stuck case doesn't pin the UI forever.
        if (Date.now() - startTime > TIMEOUT_MS) {
          setBaselineRunning(null);
          return;
        }
        try {
          const newCase = await api.getCase(newBaselineId);
          if (newCase.phase === "complete") {
            // Pull both cases full and open the Compare modal.
            const originalFull = await api.getCase(caseId);
            setModal({ kind: "compare", cases: [originalFull, newCase] });
            setBaselineRunning(null);
            refreshCases();
            return;
          }
        } catch {
          /* swallow transient fetch errors; will retry */
        }
        setTimeout(tryComplete, POLL_INTERVAL_MS);
      };
      setTimeout(tryComplete, POLL_INTERVAL_MS);
    } catch (e) {
      console.error("Baseline replay failed:", e);
      setBaselineRunning(null);
    }
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

  // W8 — full-screen Agent Run view. Swaps the whole fabric chrome
  // for the agent timeline component when the user clicks the "Agent
  // run" button in the StatusBar (or lands on /agent-run directly).
  if (agentRunOpen) {
    return (
      <AgentRun
        onExit={() => {
          setAgentRunOpen(false);
          if (typeof window !== "undefined") {
            window.history.replaceState(null, "", "/");
          }
        }}
      />
    );
  }

  return (
    <>
      {launchStatus && (
        <div
          style={{
            position: "fixed",
            top: 16,
            left: "50%",
            transform: "translateX(-50%)",
            background: "linear-gradient(135deg, #6366f1, #4338ca)",
            color: "#ffffff",
            padding: "10px 18px",
            borderRadius: 6,
            fontFamily: "'DM Mono', monospace",
            fontSize: 12,
            fontWeight: 600,
            letterSpacing: "0.04em",
            boxShadow: "0 8px 24px rgba(99, 102, 241, 0.4)",
            zIndex: 2000,
          }}
        >
          ⚡ {launchStatus}
        </div>
      )}
      <StatusBar
        active={active}
        role={role}
        user={user}
        onLogout={onLogout}
        onOpenKnowledge={() => setModal({ kind: "knowledge", tab: "sources" })}
        onOpenScenariosHelp={() => setModal({ kind: "scenarios-help" })}
        onOpenMetrics={() => setModal({ kind: "metrics" })}
        onOpenInsights={() => setModal({ kind: "insights" })}
        onOpenPlatformFlow={() => setModal({ kind: "platform-flow" })}
        onOpenCaseSpec={() => setModal({ kind: "case-spec" })}
        onOpenAgentRun={() => {
          setAgentRunOpen(true);
          if (typeof window !== "undefined") {
            window.history.pushState(null, "", "/agent-run");
          }
        }}
      />
      <div className="main">
        <Console
          scenarios={scenarios}
          cases={cases}
          active={active}
          role={role}
          composerLocked={composerLocked || isSubmitting}
          isSubmitting={isSubmitting}
          onSendPrompt={onSendPrompt}
          onConfirm={onConfirm}
          onCancel={onCancel}
          onSelectCase={setActiveId}
          onReplay={onReplay}
          onBaselineReplay={onBaselineReplay}
          onCompare={onCompare}
          onOpenReview={onOpenReview}
          onPickCandidate={onPickCandidate}
          onDeleteCase={onDeleteCase}
          onClearCompleted={onClearCompleted}
          onEditScenario={(sid) => setModal({ kind: "edit-scenario", scenarioId: sid })}
        />
        <FlowStage
          active={active}
          role={role}
          onOpenReview={onOpenReview}
          onRefresh={() => {
            refreshActive();
            refreshCases();
          }}
          onReplay={onReplay}
          onBaselineReplay={onBaselineReplay}
          onCompare={onCompare}
          baselineRunningForActive={
            !!(active && baselineRunning === active.case_id)
          }
          externalOpenNetworkSignal={networkOpenCounter}
          externalOpenPathwaysSignal={pathwaysOpenCounter}
        />
        <LineagePanel
          active={active}
          onRefresh={() => {
            refreshActive();
            refreshCases();
          }}
        />
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
      {modal.kind === "insights" && (
        <InsightsModal onClose={() => setModal({ kind: "none" })} />
      )}
      {modal.kind === "platform-flow" && (
        <PlatformFlowModal active={active} onClose={() => setModal({ kind: "none" })} />
      )}
      {modal.kind === "case-spec" && active && (
        <CaseSpecModal
          active={active}
          initialTab={modal.tab}
          initialAnchor={modal.anchor}
          onClose={() => setModal({ kind: "none" })}
        />
      )}
    </>
  );
}
