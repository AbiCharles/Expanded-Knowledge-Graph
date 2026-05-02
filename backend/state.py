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
    KnowledgeContext,
    LLMClient,
    OutboundQueue,
    ReviewDecision,
    TeamsAdaptiveCardSurface,
)

from .agent_runtime import AgentRuntime
from .auto_scenario import make_auto_scenario
from .binders import FixtureAgentBinder, FixtureProposalBinder, FixtureReviewBinder
from .case_record import CaseRecord  # re-exported below for back-compat
from .datasources import DataSourceRegistry, DataSourceSpec
from .persistence import Database, PersistentCaseStore, SqliteLineageRecorder
from .scenario_loader import ScenarioRegistry
from .sse import CaseEventBus

__all__ = ["AppState", "CaseRecord", "InMemoryQueue", "InMemoryDecisionStore"]


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
# CaseRecord lives in backend/case_record.py to break the import cycle with
# backend/persistence/case_store.py. Re-exported above for back-compat.
# =============================================================================


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
        database: Database,
    ):
        self.scenarios = scenarios
        self.llm = llm
        self.agent_runtime = agent_runtime
        self.data_sources = data_sources
        self.database = database
        self.bus = CaseEventBus()

        # Cases — dict-like API backed by SQLite. Mutations on a CaseRecord
        # (decision_kind, phase, etc.) need to call `state.cases.save(case)` to
        # persist; the orchestrator + API endpoints do that at phase boundaries.
        self.cases: PersistentCaseStore = PersistentCaseStore(database)

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
        # Lineage persists to the same SQLite DB. The framework's Protocol is
        # tiny (`record` + `history`), so the swap is invisible to the service.
        self.lineage = SqliteLineageRecorder(database)

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
