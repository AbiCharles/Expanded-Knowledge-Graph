"""
HITLContextService — the orchestrator.

Wires the three stage binders, the resolver registry, the transport, the
reviewer surface, and the lineage recorder into a single callable surface
the agent runtime invokes.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from .lineage import make_event
from .models import (
    AgentAction,
    KnowledgeContext,
    ReviewDecision,
    ReviewDecisionKind,
    ReviewTicket,
    Stage,
    TransportMode,
)
from .protocols import (
    AgentIntakeBinder,
    HITLTransport,
    LineageRecorder,
    ProposalBinder,
    ReviewBinder,
)


class HITLContextService:
    """Single-entry orchestrator for the HITL context flow."""

    def __init__(
        self,
        *,
        agent_binder: AgentIntakeBinder,
        proposal_binder: ProposalBinder,
        review_binder: ReviewBinder,
        transport: HITLTransport,
        lineage: LineageRecorder,
    ):
        self.agent_binder = agent_binder
        self.proposal_binder = proposal_binder
        self.review_binder = review_binder
        self.transport = transport
        self.lineage = lineage

    # -------------------------------------------------------------------------
    # Stage 1 — Agent intake
    # -------------------------------------------------------------------------
    def open_case(
        self,
        agent_id: str,
        scenario: dict[str, Any],
        *,
        transport_mode: TransportMode = TransportMode.ASYNC,
    ) -> KnowledgeContext:
        case_id = f"case-{uuid.uuid4().hex[:12]}"
        ctx = KnowledgeContext(
            case_id=case_id,
            correlation_id=case_id,
            agent_id=agent_id,
            action=AgentAction(
                action_id="pending",
                action_type="pending",
                actor_id=agent_id,
                payload={},
            ),
            transport_mode=transport_mode,
        )
        intake = self.agent_binder.bind(agent_id, scenario)
        ctx.attach_stage(intake)
        ev = make_event(
            stage=Stage.AGENT_INTAKE,
            actor=agent_id,
            action="bound",
            knowledge_refs=[f.ref for f in intake.facts],
            detail=f"agent intake — {len(intake.facts)} fact(s) bound",
        )
        ctx.append_lineage(ev)
        self.lineage.record(case_id, ev)
        return ctx

    # -------------------------------------------------------------------------
    # Stage 2 — Proposes Action
    # -------------------------------------------------------------------------
    def attach_proposal(self, ctx: KnowledgeContext, action: AgentAction) -> KnowledgeContext:
        ctx.action = action
        proposal = self.proposal_binder.bind(action)
        ctx.attach_stage(proposal)
        ev = make_event(
            stage=Stage.PROPOSAL,
            actor=action.actor_id,
            action="bound",
            knowledge_refs=[f.ref for f in proposal.facts],
            detail=f"proposal — {len(proposal.facts)} fact(s) bound to action {action.action_id}",
        )
        ctx.append_lineage(ev)
        self.lineage.record(ctx.case_id, ev)
        return ctx

    # -------------------------------------------------------------------------
    # Stage 3 — HITL Review (submit)
    # -------------------------------------------------------------------------
    def submit_for_review(self, ctx: KnowledgeContext) -> ReviewTicket:
        review = self.review_binder.bind(ctx.action, ctx)
        ctx.attach_stage(review)
        ticket = self.transport.submit(ctx)
        ctx.ticket = ticket
        ev = make_event(
            stage=Stage.REVIEW,
            actor="hitl_service",
            action="submitted",
            knowledge_refs=[f.ref for f in review.facts],
            detail=f"submitted ticket {ticket.ticket_id} via {ticket.transport.value}",
        )
        ctx.append_lineage(ev)
        self.lineage.record(ctx.case_id, ev)
        return ticket

    # -------------------------------------------------------------------------
    # Stage 4 — Decision arrives
    # -------------------------------------------------------------------------
    def collect_decision(
        self, ctx: KnowledgeContext, ticket_id: str
    ) -> Optional[ReviewDecision]:
        decision = self.transport.poll(ticket_id)
        if decision is None:
            return None
        ctx.decision = decision
        # Map decision kind → terminal stage:
        #   approve            → EXECUTE
        #   reject / timeout   → ABORT
        #   request_more_info  → REVIEW (loops back; no terminal)
        kind = decision.decision
        if kind == ReviewDecisionKind.APPROVE:
            stage = Stage.EXECUTE
        elif kind == ReviewDecisionKind.REQUEST_MORE_INFO:
            stage = Stage.REVIEW
        else:
            stage = Stage.ABORT
        ev = make_event(
            stage=stage,
            actor=decision.reviewer_id,
            action="decided",
            knowledge_refs=[f.ref for f in decision.additional_facts],
            detail=f"{decision.decision.value} — {decision.rationale}",
        )
        ctx.append_lineage(ev)
        self.lineage.record(ctx.case_id, ev)
        return decision
