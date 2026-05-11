"""Case lifecycle endpoints."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Optional

log = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .. import orchestrator
from ..auth import CurrentUser, current_user
from ..state import AppState, CaseRecord

router = APIRouter(tags=["cases"])


# =============================================================================
# Request / response shapes
# =============================================================================
class CreateCaseIn(BaseModel):
    """Body for POST /api/cases — operator's natural-language request."""

    prompt: str
    # Phase 3.D: when true, and the scenario classifier finds no match,
    # try parsing the prompt as an ontology NL query and synthesize a
    # one-shot autonomous SC-ADHOC-* scenario for it. Off by default so
    # existing behaviour is preserved.
    try_ontology_fallback: bool = False
    # Phase 3.E: when true, and the prior steps (classifier + ontology
    # fallback if enabled) found nothing, try the NL action picker. If
    # an action matches, synthesize an HITL SC-NLWRITE-* scenario whose
    # reviewer-approval phase invokes the action's executor.
    try_action_fallback: bool = False


class CandidateOut(BaseModel):
    """One ranked classifier candidate returned by `interpret_prompt`.

    Surfaces in CreateCaseOut.candidates so the UI can offer "Did you mean…?"
    alternatives when the top match has low confidence.
    """

    scenario_id: str
    title: str
    confidence: float


class CreateCaseOut(BaseModel):
    """Response for POST /api/cases — the new case + the agent's interpretation."""

    case_id: str
    scenario_id: Optional[str]
    interpreted_as: str
    clarifying_question: str
    confidence: float
    candidates: list[CandidateOut] = []


class ReplayIn(BaseModel):
    """Body for POST /api/cases/{id}/replay — forced decision for the new case."""

    decision: str  # "approve" | "reject" | "request_more_info"


class RelinkIn(BaseModel):
    """Body for POST /api/cases/{id}/relink — switch to a different scenario."""

    scenario_id: str


# =============================================================================
# Routes
# =============================================================================
@router.post("/cases", response_model=CreateCaseOut)
async def create_case(
    payload: CreateCaseIn,
    request: Request,
    user: CurrentUser = Depends(current_user),
) -> CreateCaseOut:
    """Operator typed a prompt. Run LLM classification, return clarifier."""
    state: AppState = request.app.state.app_state
    interpreted = await state.agent_runtime.interpret_prompt(payload.prompt)

    case_id = f"case-{uuid.uuid4().hex[:10]}"

    # Phase 3.D ad-hoc ontology fallback: when the classifier found no
    # scenario AND the operator opted in, try the NL→ontology parser
    # against every loaded ontology. First class with a non-empty mapping
    # wins. The resulting scenario is registered in-memory only (persist
    # =False, marker `_adhoc: True`) and is filtered out of the chip list.
    # Note: `interpreted.candidates` may still be populated (the classifier
    # surfaces a generic catalog on no-match), so `scenario_id is None` is
    # the load-bearing signal.
    if payload.try_ontology_fallback and interpreted.scenario_id is None:
        match = await _try_ontology_fallback(state, payload.prompt)
        if match is not None:
            from ..auto_scenario import (
                adhoc_scenario_id_for,
                make_adhoc_ontology_scenario,
            )

            adhoc_id = adhoc_scenario_id_for(case_id)
            scenario_dict = make_adhoc_ontology_scenario(
                case_id=case_id,
                ontology_id=match["ontology_id"],
                class_name=match["class"],
                where=match["where"],
                purpose=match["purpose"],
                prompt=payload.prompt,
            )
            state.scenarios.register(scenario_dict, persist=False)
            interpreted = type(interpreted)(
                scenario_id=adhoc_id,
                interpreted_as=scenario_dict["interpreted_as"],
                clarifying_question=scenario_dict["clarifying_question"],
                confidence=0.0,  # synthesized — no real classifier confidence
                candidates=[],
            )

    # Phase 3.E action fallback: only fires if the scenario classifier AND
    # the ontology fallback (if enabled) produced nothing. HITL by default
    # — write actions go through reviewer approval.
    if payload.try_action_fallback and interpreted.scenario_id is None:
        action_match = await _try_action_fallback(state, payload.prompt)
        if action_match is not None:
            from ..auto_scenario import (
                make_nlwrite_action_scenario,
                nlwrite_scenario_id_for,
            )

            action = state.actions.require(action_match.action_id)
            scenario_dict = make_nlwrite_action_scenario(
                case_id=case_id,
                action=action,
                arguments=action_match.arguments,
                rationale=action_match.rationale,
                prompt=payload.prompt,
            )
            state.scenarios.register(scenario_dict, persist=False)
            interpreted = type(interpreted)(
                scenario_id=nlwrite_scenario_id_for(case_id),
                interpreted_as=scenario_dict["interpreted_as"],
                clarifying_question=scenario_dict["clarifying_question"],
                confidence=action_match.confidence,
                candidates=[],
            )

    candidates_payload = [c.model_dump() for c in interpreted.candidates]
    # phase: we keep "awaiting_clarification" as long as we have at least one
    # candidate to suggest — the UI shows top-K buttons when confidence is low.
    has_candidates = bool(interpreted.scenario_id) or bool(candidates_payload)
    record = CaseRecord(
        case_id=case_id,
        prompt=payload.prompt,
        scenario_id=interpreted.scenario_id,
        interpreted_as=interpreted.interpreted_as,
        clarifying_question=interpreted.clarifying_question,
        user_id=user.id,
        confidence=interpreted.confidence,
        candidates=candidates_payload,
        phase="awaiting_clarification" if has_candidates else "cancelled",
    )
    state.cases[case_id] = record
    return CreateCaseOut(
        case_id=case_id,
        scenario_id=interpreted.scenario_id,
        interpreted_as=interpreted.interpreted_as,
        clarifying_question=interpreted.clarifying_question,
        confidence=interpreted.confidence,
        candidates=[CandidateOut(**c) for c in candidates_payload],
    )


async def _try_action_fallback(state, prompt: str):
    """Try the NL→action picker. Returns the NLActionMatch on success,
    None when nothing matches (or the registry is empty)."""
    from ..actions import NLActionParseError, parse_nl_action

    if not state.actions.all():
        return None
    try:
        return await parse_nl_action(prompt, state.actions, state.llm)
    except NLActionParseError as exc:
        log.info("action fallback: no match (%s)", exc)
        return None


async def _try_ontology_fallback(state, prompt: str):
    """Try parsing the prompt against every loaded ontology in turn.
    Return the first successful parse whose class has at least one source
    binding in the mapping, as a dict suitable for `make_adhoc_ontology_scenario`.
    Returns None if no ontology produced a usable match."""
    from ..ontology import NLParseError, collect_attribute_samples, parse_nl_query

    for onto in state.ontologies.all():
        # Schema-aware NL parse: collect per-attribute sample values from
        # the bound sources so the LLM can match human filter forms
        # ("Dutch") to the actual data shape ("NL").
        mapping = state.ontologies.get_mapping(onto.id)
        samples = collect_attribute_samples(onto, mapping, state.data_sources)
        try:
            oq = await parse_nl_query(
                prompt, onto, state.llm, attribute_samples=samples
            )
        except NLParseError:
            continue
        # Class must be backed by at least one source for the fallback to do
        # anything useful — otherwise the case would auto-execute and bind
        # zero facts.
        cm = mapping.for_class(oq.class_) if mapping else None
        if cm is None or not cm.sources:
            log.info(
                "ontology fallback: %s.%s parsed but has no source bindings; skipping",
                onto.id, oq.class_,
            )
            continue
        return {
            "ontology_id": onto.id,
            "class": oq.class_,
            "where": oq.where,
            "purpose": oq.purpose,
        }
    return None


def _own_case_or_403(state: AppState, case_id: str, user: CurrentUser) -> CaseRecord:
    """Look up a case; 404 if missing, 403 if it isn't the caller's case
    (admins can see everything)."""
    case = state.cases.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    if user.role != "admin" and case.user_id is not None and case.user_id != user.id:
        raise HTTPException(status_code=403, detail="not your case")
    return case


@router.post("/cases/{case_id}/confirm")
async def confirm_case(
    case_id: str, request: Request, user: CurrentUser = Depends(current_user)
) -> dict:
    """Operator confirmed; kick off the full pipeline as a background task."""
    state: AppState = request.app.state.app_state
    case = _own_case_or_403(state, case_id, user)
    if case.phase != "awaiting_clarification":
        raise HTTPException(status_code=409, detail=f"case is in phase {case.phase!r}")
    asyncio.create_task(orchestrator.run_case(state, case))
    return {"case_id": case_id, "phase": case.phase}


@router.post("/cases/{case_id}/relink")
async def relink_case(
    case_id: str, payload: RelinkIn, request: Request,
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Re-link a case to a different scenario the operator picked from top-K.

    Only allowed in `awaiting_clarification` — once binding starts, the case
    is committed. Updates interpreted_as / clarifying_question to reflect the
    new scenario's defaults.
    """
    state: AppState = request.app.state.app_state
    case = _own_case_or_403(state, case_id, user)
    if case.phase != "awaiting_clarification":
        raise HTTPException(status_code=409, detail=f"case is in phase {case.phase!r}")
    sc = state.scenarios.get(payload.scenario_id)
    if sc is None:
        raise HTTPException(status_code=404, detail="unknown scenario_id")
    case.scenario_id = sc["id"]
    case.interpreted_as = sc.get("interpreted_as", "")
    case.clarifying_question = sc.get("clarifying_question", "")
    state.cases.save(case)
    return {
        "case_id": case_id,
        "scenario_id": case.scenario_id,
        "interpreted_as": case.interpreted_as,
        "clarifying_question": case.clarifying_question,
    }


@router.delete("/cases/{case_id}")
async def delete_case(
    case_id: str, request: Request, user: CurrentUser = Depends(current_user)
) -> dict:
    """Permanently remove a case from memory.

    If the case has a pending review ticket, cancel it first.
    Sibling references on other cases are cleaned up.
    """
    state: AppState = request.app.state.app_state
    case = _own_case_or_403(state, case_id, user)
    # Best-effort cleanup. Both calls below can fail with transport errors
    # (e.g. ticket already collected) or stream-already-closed errors; in
    # both cases the right thing is to log and continue with the delete.
    if case.ticket_id and case.phase in ("review_ready", "reviewing"):
        try:
            state.transport.cancel(case.ticket_id, reason="case deleted")
        except Exception as exc:  # noqa: BLE001
            log.warning("transport.cancel failed for %s: %s", case.ticket_id, exc)
        if case.decision_event is not None and not case.decision_event.is_set():
            case.decision_event.set()
    try:
        await state.bus.close(case_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("bus.close failed for %s: %s", case_id, exc)
    # Clean sibling references on other cases
    for other in state.cases.values():
        if case_id in other.sibling_case_ids:
            other.sibling_case_ids = [s for s in other.sibling_case_ids if s != case_id]
            state.cases.save(other)
    state.cases.pop(case_id, None)
    return {"case_id": case_id, "deleted": True}


@router.delete("/cases")
async def delete_completed_cases(
    request: Request,
    user: CurrentUser = Depends(current_user),
    phase: str = "complete",
) -> dict:
    """Bulk-clear cases by phase. Default removes all completed cases owned
    by the current user (admins clear across all users)."""
    state: AppState = request.app.state.app_state
    valid_phases = {"complete", "cancelled"}
    if phase not in valid_phases:
        raise HTTPException(
            status_code=400,
            detail=f"phase must be one of {sorted(valid_phases)} (got {phase!r})",
        )
    to_remove = [
        c.case_id for c in state.cases.values()
        if c.phase == phase and (user.role == "admin" or c.user_id is None or c.user_id == user.id)
    ]
    for cid in to_remove:
        await delete_case(cid, request, user)
    return {"phase": phase, "removed": to_remove, "count": len(to_remove)}


@router.post("/cases/{case_id}/cancel")
async def cancel_case(
    case_id: str, request: Request, user: CurrentUser = Depends(current_user)
) -> dict:
    state: AppState = request.app.state.app_state
    case = _own_case_or_403(state, case_id, user)
    case.phase = "cancelled"
    state.cases.save(case)
    await state.bus.close(case_id)
    return {"case_id": case_id, "phase": case.phase}


@router.post("/cases/{case_id}/replay")
async def replay_case(
    case_id: str, payload: ReplayIn, request: Request,
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Start a sibling case that runs the same scenario but with a forced
    reviewer decision."""
    state: AppState = request.app.state.app_state
    original = _own_case_or_403(state, case_id, user)
    if original.scenario_id is None:
        raise HTTPException(status_code=400, detail="original case has no scenario")
    if payload.decision not in ("approve", "reject", "request_more_info"):
        raise HTTPException(status_code=400, detail="invalid decision")

    new_id = f"case-{uuid.uuid4().hex[:10]}"
    new_case = CaseRecord(
        case_id=new_id,
        prompt=original.prompt,
        scenario_id=original.scenario_id,
        interpreted_as=original.interpreted_as,
        clarifying_question=None,
        user_id=user.id,
        phase="binding",
        sibling_case_ids=[case_id, *original.sibling_case_ids],
        replay_decision=payload.decision,
    )
    state.cases[new_id] = new_case

    # Wire siblings on related cases
    for cid in new_case.sibling_case_ids:
        c = state.cases.get(cid)
        if c is not None and new_id not in c.sibling_case_ids:
            c.sibling_case_ids.append(new_id)

    # Auto-confirm — replays don't show the clarifying step
    asyncio.create_task(orchestrator.run_case(state, new_case))
    asyncio.create_task(_auto_decide_replay(state, new_case))
    return {"case_id": new_id, "scenario_id": new_case.scenario_id}


async def _auto_decide_replay(state: AppState, case: CaseRecord) -> None:
    """For replays: wait until the case reaches review_ready, then file the
    forced decision automatically. Picks the first quick-pick reason from the
    scenario YAML so the timing matches the original case as closely as
    possible."""
    while case.phase not in ("review_ready", "complete", "cancelled"):
        await asyncio.sleep(0.1)
    if case.phase != "review_ready" or not case.replay_decision:
        return
    scenario = state.scenarios.require(case.scenario_id)  # type: ignore[arg-type]

    rationale = ""
    if case.replay_decision != "approve":
        reasons = scenario.get("rationale_reasons", {}).get(case.replay_decision, [])
        rationale = reasons[0] if reasons else f"Replay rationale ({case.replay_decision})."

    # Reuse the decision-recording path
    from .decisions import record_decision_internal
    await record_decision_internal(
        state=state,
        case=case,
        decision=case.replay_decision,
        reviewer_id=scenario.get("reviewer_role", {}).get("name", "replay-reviewer"),
        rationale=rationale or "",
        follow_up=None,
    )


@router.get("/cases")
async def list_cases(
    request: Request, user: CurrentUser = Depends(current_user)
) -> list[dict]:
    state: AppState = request.app.state.app_state
    rows: list[dict] = []
    for c in state.cases.values():
        # Admins see everything; everyone else only their own + legacy unowned
        if user.role != "admin" and c.user_id is not None and c.user_id != user.id:
            continue
        rows.append(_case_summary(c))
    return rows


@router.get("/cases/{case_id}")
async def get_case(
    case_id: str, request: Request, user: CurrentUser = Depends(current_user)
) -> dict:
    state: AppState = request.app.state.app_state
    case = _own_case_or_403(state, case_id, user)
    return _case_full(state, case)


@router.get("/cases/{case_id}/events")
async def case_events(case_id: str, request: Request):
    """SSE stream of events for one case."""
    state: AppState = request.app.state.app_state
    if case_id not in state.cases:
        raise HTTPException(status_code=404, detail="case not found")

    async def event_generator():
        async for event in state.bus.stream(case_id):
            if await request.is_disconnected():
                break
            yield {"event": event.kind, "data": json.dumps(event.data, default=str)}

    return EventSourceResponse(event_generator())


# =============================================================================
# Serializers
# =============================================================================
def _case_summary(c: CaseRecord) -> dict:
    return {
        "case_id": c.case_id,
        "prompt": c.prompt,
        "scenario_id": c.scenario_id,
        "phase": c.phase,
        "decision_kind": c.decision_kind,
        "interpreted_as": c.interpreted_as,
        "clarifying_question": c.clarifying_question,
        "confidence": c.confidence,
        "candidates": c.candidates,
        "sibling_case_ids": c.sibling_case_ids,
        "replay_decision": c.replay_decision,
    }


def _case_full(state: AppState, c: CaseRecord) -> dict:
    out = _case_summary(c)
    out["stages"] = []
    out["lineage"] = []
    out["closing_message"] = c.closing_message
    scenario = state.scenarios.get(c.scenario_id) if c.scenario_id else None
    if scenario:
        out["scenario"] = {
            "id": scenario["id"],
            "title": scenario["title"],
            "domain": scenario["domain"],
            "autonomous": bool(scenario.get("autonomous")),
            "operator_role": scenario.get("operator_role"),
            "reviewer_role": scenario.get("reviewer_role"),
            "teams_channel": scenario.get("teams_channel"),
            "teams_headline": scenario.get("teams_headline"),
            "execute_message": scenario.get("execute_message"),
            "rationale_reasons": scenario.get("rationale_reasons", {}),
            "outcomes": scenario.get("outcomes", {}),
            "auto_approval_guardrail": scenario.get("auto_approval_guardrail"),
            "auto_approval_reason": scenario.get("auto_approval_reason"),
        }
    # After a restart, c.ctx is None but lineage is in SQLite — fetch it from
    # the persistent recorder so the operator still sees the audit trail.
    # The framework keys lineage on its own internal case_id (different from
    # ours); we captured that as framework_case_id at intake-bind time.
    if c.ctx is None and c.framework_case_id:
        try:
            persisted = state.lineage.history(c.framework_case_id)
            if persisted:
                out["lineage"] = [ev.model_dump(mode="json") for ev in persisted]
        except Exception as exc:  # noqa: BLE001
            # Lineage is best-effort here — the case still renders without it
            log.warning("lineage history fetch failed for %s: %s", c.case_id, exc)
    if c.ctx is not None:
        out["stages"] = [
            {
                "stage": stage.value,
                "binder": sc.bound_by,
                "facts": [
                    {
                        "source": f.ref.source,
                        "ontology_type": f.ref.ontology_type,
                        "id": f.ref.id,
                        "uri": f.ref.uri,
                        "title": f.payload.get("title"),
                        "summary": f.payload.get("summary"),
                        "via_ontology": f.payload.get("via_ontology"),
                        "via_source_binding": f.payload.get("via_source_binding"),
                    }
                    for f in sc.facts
                ],
            }
            for stage, sc in c.ctx.stages.items()
        ]
        out["lineage"] = [ev.model_dump(mode="json") for ev in c.ctx.lineage]
    return out
