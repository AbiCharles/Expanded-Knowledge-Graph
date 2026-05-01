"""
TCS Agentic AI Platform — HITL Context Framework
Typed envelope for knowledge-context propagation across the HITL flow:

    Agent ─► Proposes Action ─► HITL Review ─► {Approve → Execute | Reject → Abort}

The same KnowledgeContext object is enriched at each entry point and persisted
across sync and async transports.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Stage enum — maps to the four nodes in Kevin's diagram
# =============================================================================

class Stage(str, Enum):
    AGENT_INTAKE = "agent_intake"      # Agent node — seeds reasoning
    PROPOSAL = "proposal"              # Proposes Action — binds proposal to knowledge
    REVIEW = "review"                  # HITL Review — reviewer evidence package
    EXECUTE = "execute"                # Approved → Agent Executes
    ABORT = "abort"                    # Rejected → Agent Aborts


class TransportMode(str, Enum):
    SYNC = "sync"
    ASYNC = "async"


class ReviewDecisionKind(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_MORE_INFO = "request_more_info"
    TIMEOUT = "timeout"


class TruthSourceMode(str, Enum):
    """How a KnowledgeFact is materialized."""
    SNAPSHOT_ONLY = "snapshot_only"    # embedded payload, no live link
    LINK_ONLY = "link_only"            # uri only, no embedded payload
    HYBRID = "hybrid"                  # both — default policy


# =============================================================================
# Knowledge primitives
# =============================================================================

class KnowledgeRef(BaseModel):
    """Typed pointer to a knowledge entity in an upstream source."""
    model_config = ConfigDict(extra="forbid")

    source: str                          # e.g. "kf:graph", "kf:ontology", "erp:vendor_master"
    ontology_type: str                   # ontology class, e.g. "Vendor", "Contract", "SanctionedEntity"
    id: str                              # entity ID within the source
    version: Optional[str] = None        # version / timestamp / commit
    uri: Optional[str] = None            # back-link for drill-through


class KnowledgeFact(BaseModel):
    """A single piece of knowledge bound for a stage. Carries snapshot + ref."""
    model_config = ConfigDict(extra="forbid")

    ref: KnowledgeRef
    payload: dict[str, Any] = Field(default_factory=dict)
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    truth_mode: TruthSourceMode = TruthSourceMode.HYBRID
    fetched_by: str                      # which resolver produced this fact
    confidence: Optional[float] = None   # for retrieved/inferred facts


class KnowledgeQuery(BaseModel):
    """Query passed to a KnowledgeResolver."""
    model_config = ConfigDict(extra="forbid")

    ontology_type: str
    filters: dict[str, Any] = Field(default_factory=dict)
    as_of: Optional[datetime] = None     # point-in-time queries for audit replay
    max_results: int = 50
    requested_by: str                    # binder / stage that issued the query
    purpose: str                         # human-readable rationale (audited)


# =============================================================================
# Stage context — what each node attaches to the envelope
# =============================================================================

class StageContext(BaseModel):
    """Knowledge attached at one stage of the flow."""
    model_config = ConfigDict(extra="forbid")

    stage: Stage
    facts: list[KnowledgeFact] = Field(default_factory=list)
    queries_issued: list[KnowledgeQuery] = Field(default_factory=list)
    bound_by: str                        # binder name/version
    bound_at: datetime = Field(default_factory=datetime.utcnow)
    notes: Optional[str] = None


# =============================================================================
# Lineage — append-only audit trail
# =============================================================================

class LineageEvent(BaseModel):
    """One entry in the lineage log. Append-only."""
    model_config = ConfigDict(extra="forbid")

    sequence: int
    stage: Stage
    actor: str                           # agent id / binder name / reviewer id
    action: str                          # 'fetched' | 'bound' | 'submitted' | 'decided' | ...
    knowledge_refs: list[KnowledgeRef] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    detail: Optional[str] = None


# =============================================================================
# Action envelope — wire-compatible with the SC Guardrails AgentAction
# =============================================================================

class AgentAction(BaseModel):
    """Standard envelope for any action proposed by an agent."""
    model_config = ConfigDict(extra="allow")

    action_id: str
    action_type: str
    actor_id: str
    domain: str = "supply_chain"
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# Review primitives
# =============================================================================

class ReviewTicket(BaseModel):
    """Returned when a context is submitted for review."""
    ticket_id: str
    case_id: str
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    transport: TransportMode
    callback_url: Optional[str] = None   # async only
    expires_at: Optional[datetime] = None


class ReviewDecision(BaseModel):
    """Reviewer's decision."""
    ticket_id: str
    case_id: str
    decision: ReviewDecisionKind
    reviewer_id: str
    rationale: str
    decided_at: datetime = Field(default_factory=datetime.utcnow)
    additional_facts: list[KnowledgeFact] = Field(default_factory=list)


# =============================================================================
# Top-level envelope
# =============================================================================

class KnowledgeContext(BaseModel):
    """
    The single envelope that flows through every node. Stages are added in
    order; lineage records every fetch/bind/submit/decide event.
    """
    model_config = ConfigDict(extra="forbid")

    case_id: str
    correlation_id: str
    agent_id: str
    action: AgentAction
    transport_mode: TransportMode
    stages: dict[Stage, StageContext] = Field(default_factory=dict)
    lineage: list[LineageEvent] = Field(default_factory=list)
    ticket: Optional[ReviewTicket] = None
    decision: Optional[ReviewDecision] = None

    # ---- helpers ------------------------------------------------------------
    def attach_stage(self, ctx: StageContext) -> None:
        self.stages[ctx.stage] = ctx

    def all_facts(self) -> list[KnowledgeFact]:
        out: list[KnowledgeFact] = []
        for s in self.stages.values():
            out.extend(s.facts)
        return out

    def append_lineage(self, ev: LineageEvent) -> None:
        ev.sequence = len(self.lineage)
        self.lineage.append(ev)
