"""
Protocols defining the framework's pluggable surfaces.

Implementations are deployment-specific:
  - KnowledgeResolver  → KF Knowledge Graph Runtime, master data systems, RAG indices
  - StageBinder        → one per stage; encapsulates which queries to issue
  - HITLTransport      → in-process callable (sync) OR durable queue (async)
  - LineageRecorder    → in-memory, file, or governance audit store
  - ReviewerSurface    → Teams Adaptive Card, web UI, ServiceNow, etc.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from .models import (
    AgentAction,
    KnowledgeContext,
    KnowledgeFact,
    KnowledgeQuery,
    LineageEvent,
    ReviewDecision,
    ReviewTicket,
    Stage,
    StageContext,
)


# =============================================================================
# Knowledge resolution
# =============================================================================

@runtime_checkable
class KnowledgeResolver(Protocol):
    """Source-side: turns KnowledgeQuery objects into KnowledgeFacts."""

    name: str

    def resolve(self, query: KnowledgeQuery) -> list[KnowledgeFact]: ...


@runtime_checkable
class KnowledgeResolverRegistry(Protocol):
    """Routes queries to the right resolver based on ontology_type / source."""

    def resolver_for(self, ontology_type: str, source_hint: Optional[str] = None) -> KnowledgeResolver: ...


# =============================================================================
# Stage binders — one per node in Kevin's diagram
# =============================================================================

@runtime_checkable
class AgentIntakeBinder(Protocol):
    """Seeds the agent with the knowledge it needs to reason at all.

    Called BEFORE the agent proposes an action. Examples of what it binds:
    relevant policies, recent decisions, applicable ontology classes, the
    user's permission scope, the active scenario or case file.
    """
    def bind(self, agent_id: str, scenario: dict[str, Any]) -> StageContext: ...


@runtime_checkable
class ProposalBinder(Protocol):
    """Enriches the agent's proposal envelope with bound knowledge.

    Called AFTER the agent has drafted an action but BEFORE it leaves the agent
    runtime. Binds master-data references, ontology types, contractual context,
    and any deterministic facts the proposal depends on.
    """
    def bind(self, action: AgentAction) -> StageContext: ...


@runtime_checkable
class ReviewBinder(Protocol):
    """Assembles the reviewer's evidence package.

    Called WHEN a proposal needs human review. Binds: the proposal envelope,
    upstream guardrail decisions and evidence, related prior cases, applicable
    SOPs/policies, master data records referenced by the proposal, and any
    additional knowledge needed to make a confident decision.
    """
    def bind(self, action: AgentAction, prior: KnowledgeContext) -> StageContext: ...


# =============================================================================
# Transport — sync vs async, same context contract
# =============================================================================

@runtime_checkable
class HITLTransport(Protocol):
    """
    Submits a KnowledgeContext for human review and retrieves the decision.
    Sync impl blocks/polls; async impl returns a ticket and signals via callback.
    """

    def submit(self, ctx: KnowledgeContext) -> ReviewTicket: ...

    def poll(self, ticket_id: str) -> Optional[ReviewDecision]: ...

    def cancel(self, ticket_id: str, reason: str) -> None: ...


# =============================================================================
# Reviewer surface — what the human sees
# =============================================================================

@runtime_checkable
class ReviewerSurface(Protocol):
    """
    Renders a KnowledgeContext into a reviewer-facing artifact (Teams card,
    web view, ServiceNow form, etc.) and accepts decisions back.
    """

    name: str  # e.g. "teams_adaptive_card_v1"

    def render(self, ctx: KnowledgeContext) -> dict[str, Any]: ...

    def parse_decision(self, payload: dict[str, Any]) -> ReviewDecision: ...


# =============================================================================
# Lineage
# =============================================================================

@runtime_checkable
class LineageRecorder(Protocol):
    """Append-only sink for LineageEvent records."""

    def record(self, case_id: str, event: LineageEvent) -> None: ...

    def history(self, case_id: str) -> list[LineageEvent]: ...
