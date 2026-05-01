"""
Transport implementations — same KnowledgeContext contract, different wires.

  SyncInProcessTransport   blocks on a callable surface (used for tests, demos,
                           or when the reviewer is co-located with the agent
                           runtime, e.g. an interactive desktop scenario).

  AsyncQueueTransport      writes the context to a durable queue and returns a
                           ticket; the agent suspends and resumes when the
                           decision arrives. Production default for any
                           multi-tenant or long-lived review.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from .models import (
    KnowledgeContext,
    ReviewDecision,
    ReviewTicket,
    TransportMode,
)
from .protocols import HITLTransport, ReviewerSurface


class SyncInProcessTransport:
    """Sync transport — invokes the reviewer surface in-process and blocks."""

    def __init__(
        self,
        surface: ReviewerSurface,
        decision_callable: Callable[[dict[str, Any]], dict[str, Any]],
    ):
        """
        decision_callable: takes the rendered card payload, returns the decision
        payload. In production this is the surface SDK's blocking call; in tests
        it's typically a fixture function.
        """
        self.surface = surface
        self.decision_callable = decision_callable
        self._tickets: dict[str, ReviewDecision] = {}

    def submit(self, ctx: KnowledgeContext) -> ReviewTicket:
        ticket_id = f"sync-{uuid.uuid4().hex[:12]}"
        ticket = ReviewTicket(
            ticket_id=ticket_id,
            case_id=ctx.case_id,
            transport=TransportMode.SYNC,
        )
        rendered = self.surface.render(ctx)
        decision_payload = self.decision_callable(rendered)
        decision = self.surface.parse_decision(decision_payload)
        decision.ticket_id = ticket_id
        decision.case_id = ctx.case_id
        self._tickets[ticket_id] = decision
        return ticket

    def poll(self, ticket_id: str) -> Optional[ReviewDecision]:
        return self._tickets.get(ticket_id)

    def cancel(self, ticket_id: str, reason: str) -> None:
        self._tickets.pop(ticket_id, None)


class AsyncQueueTransport:
    """
    Async transport — writes to a durable queue and exposes ticket / poll.

    The Queue protocol below is intentionally minimal so it can be backed by
    Kafka, SQS, Redis Streams, ADO Service Bus, etc. The surface receives
    rendered payloads and posts decisions back onto a decision queue.
    """

    def __init__(
        self,
        review_queue: "OutboundQueue",
        decision_store: "DecisionStore",
        surface: ReviewerSurface,
        ttl_minutes: int = 60 * 24,
    ):
        self.review_queue = review_queue
        self.decision_store = decision_store
        self.surface = surface
        self.ttl_minutes = ttl_minutes

    def submit(self, ctx: KnowledgeContext) -> ReviewTicket:
        ticket_id = f"async-{uuid.uuid4().hex[:12]}"
        ticket = ReviewTicket(
            ticket_id=ticket_id,
            case_id=ctx.case_id,
            transport=TransportMode.ASYNC,
            expires_at=datetime.utcnow() + timedelta(minutes=self.ttl_minutes),
        )
        rendered = self.surface.render(ctx)
        self.review_queue.put({
            "ticket_id": ticket_id,
            "case_id": ctx.case_id,
            "context": ctx.model_dump(mode="json"),
            "rendered": rendered,
        })
        return ticket

    def poll(self, ticket_id: str) -> Optional[ReviewDecision]:
        return self.decision_store.get(ticket_id)

    def cancel(self, ticket_id: str, reason: str) -> None:
        self.decision_store.cancel(ticket_id, reason)


# =============================================================================
# Minimal queue / store interfaces (Protocol-typed, backend-agnostic)
# =============================================================================

class OutboundQueue:
    """Implement against Kafka / SQS / Service Bus."""
    def put(self, message: dict[str, Any]) -> None:
        raise NotImplementedError


class DecisionStore:
    """Implement against Redis / DB / KV."""
    def get(self, ticket_id: str) -> Optional[ReviewDecision]:
        raise NotImplementedError

    def put(self, decision: ReviewDecision) -> None:
        raise NotImplementedError

    def cancel(self, ticket_id: str, reason: str) -> None:
        raise NotImplementedError
