"""Application state — singletons held on the FastAPI app for the duration of the process.

In-memory only. A restart wipes everything. Production deployments would
replace `InMemoryQueue` / `InMemoryDecisionStore` with Kafka + Redis, swap
`InMemoryLineageRecorder` for the governance audit-store recorder, and that's it.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from tcs_hitl_context import (
    AsyncQueueTransport,
    DecisionStore,
    HITLContextService,
    InMemoryLineageRecorder,
    KnowledgeContext,
    LLMClient,
    OutboundQueue,
    ReviewDecision,
    TeamsAdaptiveCardSurface,
)

from .agent_runtime import AgentRuntime
from .auto_scenario import make_auto_scenario
from .binders import FixtureAgentBinder, FixtureProposalBinder, FixtureReviewBinder
from .datasources import DataSourceRegistry, DataSourceSpec
from .scenario_loader import ScenarioRegistry
from .sse import CaseEventBus


# =============================================================================
# In-memory transport backends
# =============================================================================
class InMemoryQueue(OutboundQueue):
    """Production swaps this for Kafka / SQS / Service Bus."""

    def __init__(self) -> None:
        self._messages: list[dict[str, Any]] = []

    def put(self, message: dict[str, Any]) -> None:
        self._messages.append(message)

    def by_ticket(self, ticket_id: str) -> Optional[dict[str, Any]]:
        for m in self._messages:
            if m.get("ticket_id") == ticket_id:
                return m
        return None

    def all_pending(self) -> list[dict[str, Any]]:
        return list(self._messages)


class InMemoryDecisionStore(DecisionStore):
    """Production swaps this for Redis / DB / KV."""

    def __init__(self) -> None:
        self._decisions: dict[str, ReviewDecision] = {}
        self._cancellations: dict[str, str] = {}

    def get(self, ticket_id: str) -> Optional[ReviewDecision]:
        return self._decisions.get(ticket_id)

    def put(self, decision: ReviewDecision) -> None:
        self._decisions[decision.ticket_id] = decision

    def cancel(self, ticket_id: str, reason: str) -> None:
        self._cancellations[ticket_id] = reason


# =============================================================================
# Per-case bookkeeping
# =============================================================================
@dataclass
class CaseRecord:
    """One operator-initiated case + everything needed to resume it.

    `phase` mirrors the frontend's state machine and is the source of truth
    for what the UI should show.
    """

    case_id: str
    prompt: str
    scenario_id: Optional[str]
    interpreted_as: Optional[str]
    clarifying_question: Optional[str]
    confidence: float = 0.0
    candidates: list[dict] = field(default_factory=list)  # [{scenario_id, title, confidence}]
    phase: str = "awaiting_clarification"
    # awaiting_clarification | binding | review_ready | reviewing | complete | cancelled
    ctx: Optional[KnowledgeContext] = None
    ticket_id: Optional[str] = None
    decision_kind: Optional[str] = None  # approve | reject | request_more_info | auto_execute
    rationale: Optional[str] = None
    follow_up: Optional[str] = None
    sibling_case_ids: list[str] = field(default_factory=list)
    replay_decision: Optional[str] = None
    closing_message: Optional[str] = None
    # asyncio.Event signalling that a decision has been recorded for this case's ticket
    decision_event: Optional[asyncio.Event] = None


# =============================================================================
# AppState — the FastAPI singleton
# =============================================================================
class AppState:
    def __init__(
        self,
        *,
        scenarios: ScenarioRegistry,
        llm: LLMClient,
        agent_runtime: AgentRuntime,
        data_sources: DataSourceRegistry,
    ):
        self.scenarios = scenarios
        self.llm = llm
        self.agent_runtime = agent_runtime
        self.data_sources = data_sources
        self.bus = CaseEventBus()

        # Cases keyed by case id
        self.cases: dict[str, CaseRecord] = {}

        # Transport: in-memory queue + decision store. The framework writes
        # rendered cards into the queue on submit_for_review; the decisions API
        # writes ReviewDecisions into the store; collect_decision pulls them out.
        self.review_queue = InMemoryQueue()
        self.decision_store = InMemoryDecisionStore()
        self.surface = TeamsAdaptiveCardSurface()
        self.transport = AsyncQueueTransport(
            review_queue=self.review_queue,
            decision_store=self.decision_store,
            surface=self.surface,
        )
        self.lineage = InMemoryLineageRecorder()

        # Wire the framework
        self.service = HITLContextService(
            agent_binder=FixtureAgentBinder(scenarios, data_sources),
            proposal_binder=FixtureProposalBinder(scenarios, data_sources),
            review_binder=FixtureReviewBinder(scenarios, data_sources),
            transport=self.transport,
            lineage=self.lineage,
        )

        # Auto-scenario lifecycle: every operator-registered source gets a
        # corresponding chip in the operator console.
        def _on_source_register(spec: DataSourceSpec) -> None:
            scenarios.register(make_auto_scenario(spec))

        def _on_source_remove(source_id: str) -> None:
            scenarios.unregister(f"SC-AUTO-{source_id}")

        data_sources.set_lifecycle_hooks(
            on_register=_on_source_register,
            on_remove=_on_source_remove,
        )

        # Backfill auto-scenarios for any operator-registered sources that
        # already exist in sources.yaml (e.g. from a previous run).
        for spec in data_sources.specs():
            if not spec.default:
                auto_id = f"SC-AUTO-{spec.id}"
                if scenarios.get(auto_id) is None:
                    scenarios.register(make_auto_scenario(spec))

    # -------------------------------------------------------------------------
    # Convenience lookups
    # -------------------------------------------------------------------------
    def case_for_ticket(self, ticket_id: str) -> Optional[CaseRecord]:
        for c in self.cases.values():
            if c.ticket_id == ticket_id:
                return c
        return None
