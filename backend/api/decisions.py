"""Reviewer decision endpoint."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from tcs_hitl_context import ReviewDecision, ReviewDecisionKind

from ..state import AppState, CaseRecord

router = APIRouter(tags=["decisions"])


class RecordDecisionIn(BaseModel):
    decision: str  # approve | reject | request_more_info
    reviewer_id: str = "reviewer"
    rationale: str = ""
    follow_up: Optional[str] = None


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
) -> dict:
    """Write the decision into the framework's decision store and signal the
    orchestrator that's blocked waiting for it."""
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

    case.phase = "reviewing"
    state.cases.save(case)
    if case.decision_event is not None:
        case.decision_event.set()

    return {"case_id": case.case_id, "ticket_id": case.ticket_id, "decision": decision}
