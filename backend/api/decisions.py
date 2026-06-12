"""Reviewer decision endpoint."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from tcs_hitl_context import ReviewDecision, ReviewDecisionKind

from ..state import AppState, CaseRecord


# Phase 2 — reviewer-flagged load-bearing facts. Capped at 3 to keep the
# Phase 3 mining signal sharp; more than that and "load-bearing" loses
# meaning.
MAX_HIGHLIGHTED_FACTS = 3


class HighlightedFactRef(BaseModel):
    """A reviewer-marked fact reference. Triple matches `KnowledgeRef` so
    Phase 3 can join straight against the lineage."""
    source: str = Field(min_length=1)
    ontology_type: str = Field(min_length=1)
    id: str = Field(min_length=1)
    title: Optional[str] = None

router = APIRouter(tags=["decisions"])


class RecordDecisionIn(BaseModel):
    decision: str  # approve | reject | request_more_info
    reviewer_id: str = "reviewer"
    rationale: str = ""
    follow_up: Optional[str] = None
    # Phase 2 — optional list of facts the reviewer flagged as
    # load-bearing in the decision. Order matters (most → least).
    highlighted_fact_refs: list[HighlightedFactRef] = Field(default_factory=list)


@router.get("/decisions/queue")
def list_pending(request: Request) -> list[dict]:
    """Pending review tickets — what a reviewer surface would show as a feed."""
    state: AppState = request.app.state.app_state
    out: list[dict] = []
    for msg in state.review_queue.all_pending():
        ticket_id = msg.get("ticket_id")
        case = state.case_for_ticket(ticket_id) if ticket_id else None
        if case is None or case.phase != "review_ready":
            continue
        out.append(
            {
                "ticket_id": ticket_id,
                "case_id": case.case_id,
                "scenario_id": case.scenario_id,
                "rendered_card": msg.get("rendered"),
            }
        )
    return out


@router.post("/decisions/{ticket_id}")
async def post_decision(ticket_id: str, payload: RecordDecisionIn, request: Request) -> dict:
    # Static-payload validation first — return a 4xx on bad shape before
    # touching the case store. Saves a DB hit and keeps error semantics
    # crisp for clients (bad request != not found).
    if len(payload.highlighted_fact_refs) > MAX_HIGHLIGHTED_FACTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"at most {MAX_HIGHLIGHTED_FACTS} highlighted_fact_refs allowed "
                f"(got {len(payload.highlighted_fact_refs)})"
            ),
        )
    state: AppState = request.app.state.app_state
    case = state.case_for_ticket(ticket_id)
    if case is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    if case.phase != "review_ready":
        raise HTTPException(status_code=409, detail=f"case is in phase {case.phase!r}")
    return await record_decision_internal(
        state=state,
        case=case,
        decision=payload.decision,
        reviewer_id=payload.reviewer_id,
        rationale=payload.rationale,
        follow_up=payload.follow_up,
        highlighted_fact_refs=[ref.model_dump() for ref in payload.highlighted_fact_refs],
    )


# Reusable by replay logic in cases.py
async def record_decision_internal(
    *,
    state: AppState,
    case: CaseRecord,
    decision: str,
    reviewer_id: str,
    rationale: str,
    follow_up: Optional[str],
    highlighted_fact_refs: Optional[list[dict]] = None,
) -> dict:
    """Write the decision into the framework's decision store and signal the
    orchestrator that's blocked waiting for it.

    `highlighted_fact_refs` (Phase 2) is the reviewer's optional list of
    load-bearing facts. We stash it on the case *before* unblocking the
    orchestrator so the orchestrator can write the denormalised table
    once the case completes.
    """
    if decision not in {"approve", "reject", "request_more_info"}:
        raise HTTPException(status_code=400, detail="invalid decision kind")
    if not case.ticket_id:
        raise HTTPException(status_code=409, detail="case has no ticket")

    rd = ReviewDecision(
        ticket_id=case.ticket_id,
        case_id=case.case_id,
        decision=ReviewDecisionKind(decision),
        reviewer_id=reviewer_id or "reviewer",
        rationale=rationale or "",
        decided_at=datetime.utcnow(),
    )
    state.decision_store.put(rd)
    case.follow_up = follow_up
    # Stash highlights now so the orchestrator can pick them up after its
    # decision_event wakes. Empty list when the reviewer skipped (or for
    # auto-approve / replay paths that don't pass any).
    case.highlighted_fact_refs = list(highlighted_fact_refs or [])

    case.phase = "reviewing"
    state.cases.save(case)
    if case.decision_event is not None:
        case.decision_event.set()

    return {"case_id": case.case_id, "ticket_id": case.ticket_id, "decision": decision}
