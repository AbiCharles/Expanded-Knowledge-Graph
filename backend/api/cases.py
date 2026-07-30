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
from ..agent_runtime import RouteResult
from ..auth import CurrentUser, current_user
from ..case_history import decision_history_provider
from ..outcome_plan import OutcomePlan
from ..pipeline import PipelineRecord, PipelineStepState
from ..rag_answerer import RagAnswer, answer_via_rag
from ..scenario_composer import compose
from ..scenario_determinism import is_deterministic
from ..state import AppState, CaseRecord

router = APIRouter(tags=["cases"])


# =============================================================================
# Request / response shapes
# =============================================================================
class CreateCaseIn(BaseModel):
    """Body for POST /api/cases — operator's natural-language request."""

    prompt: str


class CandidateOut(BaseModel):
    """One ranked classifier candidate returned by `interpret_prompt`.

    Surfaces in CreateCaseOut.candidates so the UI can offer "Did you mean…?"
    alternatives when the top match has low confidence.
    """

    scenario_id: str
    title: str
    confidence: float


class PipelineStepOut(BaseModel):
    """One scenario in a planned multi-scenario pipeline (in run order)."""

    scenario_id: str
    title: str
    why: str = ""


class PipelineOut(BaseModel):
    """Attached to CreateCaseOut when a question spans multiple scenarios.

    `forecast` is the probability-weighted Outcome DAG projected for the
    planned pipeline (same shape as POST /graph/outcome-tree). Phase 1
    surfaces this as the projected map; Phase 2 will drive the real
    chained execution from `steps`.
    """

    pipeline_id: str
    steps: list[PipelineStepOut]
    rationale: str = ""
    confidence: float = 0.0
    forecast: OutcomePlan


class CreateCaseOut(BaseModel):
    """Response for POST /api/cases — the new case + the agent's interpretation."""

    case_id: str
    scenario_id: Optional[str]
    interpreted_as: str
    clarifying_question: str
    confidence: float
    candidates: list[CandidateOut] = []
    # Populated only when the planner decides the question spans 2+
    # scenarios. Null for ordinary single-scenario questions (unchanged flow).
    pipeline: Optional[PipelineOut] = None
    # The answer-strategy router's A/B/C distribution + chosen strategy. Always
    # present; drives the 3-way bar shown the instant a question is sent.
    routing: Optional[RouteResult] = None
    # The generative answer, present only when the router chose Strategy C (RAG).
    rag: Optional[RagAnswer] = None


class ReplayIn(BaseModel):
    """Body for POST /api/cases/{id}/replay.

    Two modes:
      • Forced-decision replay (default) — sets `decision` to one of
        "approve" / "reject" / "request_more_info"; the sibling case runs
        normally and the decision is auto-filed once review_ready.
      • Baseline replay (W5 / Beat 2) — `baseline=true`. The sibling
        case runs with the REVIEW STAGE QUERIES STRIPPED so the result
        shows what a "supervisor without the governed knowledge layer"
        would have surfaced. Decision auto-defaults to "approve" since
        a baseline reviewer without the governance evidence is most
        likely to greenlight the proposed action."""

    decision: Optional[str] = None  # required unless baseline=True
    baseline: bool = False


class RelinkIn(BaseModel):
    """Body for POST /api/cases/{id}/relink — switch to a different scenario."""

    scenario_id: str


class ReviseIn(BaseModel):
    """Body for POST /api/cases/{id}/revise — W1 / Beat 3 (case revisioning).

    A trigger_id picks one of the narrative triggers from TRIGGER_CATALOG
    or the special value "generic_refresh" (re-snapshot current state)."""

    trigger_id: str


# W1 / Beat 3 — trigger catalog. Each entry knows which scenario(s) it
# applies to, the fact to inject into a target stage, and the decision
# the harness would re-recommend after seeing the new evidence. Designed
# for the Aeronova narrative; extending to other scenarios is a YAML edit
# away (this dict could live in a config file once the catalog grows).
TRIGGER_CATALOG: dict[str, dict] = {
    "ironcrest_qual_lapsed": {
        "label": "Ironcrest qualification just lapsed",
        "applies_to_scenarios": ["SC-PP-AERONOVA-026"],
        "inject": {
            "stage": "proposal",
            "fact": {
                "source": "kf:context",
                "ontology_type": "QualificationUpdate",
                "id": "QUAL-SUP-023-LAPSE",
                "uri": None,
                "title": "Ironcrest Metalworks (SUP-023) · qualification lapsed",
                "summary": (
                    "Quality certification expired 2026-07-30 · qualification: "
                    "lapsed effective immediately · Ironcrest can no longer "
                    "ship to flagship-program SKUs without re-certification."
                ),
                "via_ontology": None,
                "via_source_binding": None,
                "query_index": None,
                "hops": None,
                "tier": None,
                "status": "lapsed",
                "via_path": None,
                "via_node_id": None,
            },
        },
        "new_decision": "reject",
        "explainer": (
            "Ironcrest's quality certification just expired. The harness "
            "re-decides: reject the swap. Both v1 (original approval) and "
            "v2 (rejection) remain on the audit trail."
        ),
    },
    "new_sdn_listing": {
        "label": "New SDN listing puts Ironcrest within 2 hops",
        "applies_to_scenarios": ["SC-PP-AERONOVA-026"],
        "inject": {
            "stage": "proposal",
            "fact": {
                "source": "kf:graph",
                "ontology_type": "SanctionsProximity",
                "id": "SDN-NET-007",
                "uri": None,
                "title": "Vega Marine Trading (OFAC SDN · added 2026-07-31)",
                "summary": (
                    "2-hop trail · HIGH risk · Ironcrest (SUP-023) → "
                    "Northgate Sister Holdings → Vega Marine Trading · "
                    "listed 2026-07-31"
                ),
                "via_ontology": None,
                "via_source_binding": None,
                "query_index": None,
                "hops": 2,
                "tier": None,
                "status": None,
                "via_path": (
                    "indirect ownership via Northgate Sister Holdings"
                ),
                "via_node_id": None,
            },
        },
        "new_decision": "reject",
        "explainer": (
            "OFAC just listed a new SDN that puts Ironcrest at 2-hop "
            "proximity through an indirect-ownership chain. The harness "
            "re-decides: reject the swap."
        ),
    },
}


def _triggers_for_scenario(scenario_id: Optional[str]) -> list[dict]:
    return [
        {
            "id": tid,
            "label": t["label"],
            "explainer": t.get("explainer", ""),
        }
        for tid, t in TRIGGER_CATALOG.items()
        if not t["applies_to_scenarios"]
        or (scenario_id and scenario_id in t["applies_to_scenarios"])
    ]


# =============================================================================
# Routes
# =============================================================================
@router.post("/cases", response_model=CreateCaseOut)
async def create_case(
    payload: CreateCaseIn,
    request: Request,
    user: CurrentUser = Depends(current_user),
) -> CreateCaseOut:
    """Operator typed a prompt. Run LLM classification, return clarifier.

    Also runs the pipeline planner: if the question spans 2+ dependent
    scenarios, the response carries a `pipeline` block (the planned steps +
    a probability-weighted forecast graph). The single case created here is
    still the entry point; Phase 2 will drive the real chained execution.
    """
    state: AppState = request.app.state.app_state
    # Classify (single-scenario) and plan (multi-scenario) concurrently — both
    # depend only on the prompt and fall back internally (never raise), so this
    # halves the classification latency before the routing step.
    interpreted, plan = await asyncio.gather(
        state.agent_runtime.interpret_prompt(payload.prompt),
        state.agent_runtime.plan_pipeline(payload.prompt),
    )

    # Project the Outcome DAG only when the plan is genuinely multi-scenario.
    forecast = None
    if plan.multi:
        try:
            forecast = compose(
                payload.prompt,
                [s.scenario_id for s in plan.steps],
                scenarios=state.scenarios,
                history_provider=decision_history_provider(state.database),
                context={},
            )
        except Exception:
            log.exception("outcome forecast failed; continuing as single case")
            forecast = None

    is_multi = plan.multi and forecast is not None

    # Answer-strategy router: score A/B/C, then auto-run the winner. C answers
    # generatively here; A forces the single deterministic scenario; B keeps the
    # multi-scenario pipeline. route_query never raises (heuristic fallback).
    top_sc = state.scenarios.get(interpreted.scenario_id) if interpreted.scenario_id else None
    route = state.agent_runtime.route_query(
        interpreted, plan,
        top_is_deterministic=bool(top_sc) and is_deterministic(top_sc),
    )
    rag_answer: Optional[RagAnswer] = None
    if route.strategy == "rag":
        is_multi = False
        rag_answer = await answer_via_rag(state, payload.prompt)
    elif route.strategy == "single":
        is_multi = False

    case_id = f"case-{uuid.uuid4().hex[:10]}"
    pipeline_id = f"pipe-{uuid.uuid4().hex[:10]}" if is_multi else None

    candidates_payload = [c.model_dump() for c in interpreted.candidates]
    # phase: we keep "awaiting_clarification" as long as we have at least one
    # candidate to suggest (or this is a pipeline entry point) — the UI shows
    # top-K buttons / the "Run pipeline" affordance from there.
    has_candidates = bool(interpreted.scenario_id) or bool(candidates_payload)

    # When multi, the entry-point case runs the pipeline's FIRST step (which
    # may differ from the single-scenario classification); otherwise it runs
    # the classifier's best match.
    if is_multi:
        first_scenario: Optional[str] = plan.steps[0].scenario_id
        sc0 = state.scenarios.get(first_scenario) or {}
        interpreted_as = sc0.get("interpreted_as", "")
        clarifying_question = sc0.get("clarifying_question", "")
    else:
        first_scenario = interpreted.scenario_id
        interpreted_as = interpreted.interpreted_as
        clarifying_question = interpreted.clarifying_question

    # Pin the case to the live scenario's current version so a later edit
    # (which bumps the scenario to v+1) doesn't retroactively change what
    # this case ran against.
    scenario_version = None
    if first_scenario:
        sc = state.scenarios.get(first_scenario)
        if sc and isinstance(sc.get("version"), int):
            scenario_version = sc["version"]

    record = CaseRecord(
        case_id=case_id,
        prompt=payload.prompt,
        scenario_id=first_scenario,
        scenario_version=scenario_version,
        interpreted_as=interpreted_as,
        clarifying_question=clarifying_question,
        user_id=user.id,
        confidence=interpreted.confidence,
        candidates=candidates_payload,
        phase="awaiting_clarification" if (has_candidates or is_multi) else "cancelled",
        pipeline_id=pipeline_id,
        pipeline_step=0 if is_multi else None,
    )
    state.cases[case_id] = record

    pipeline_out: Optional[PipelineOut] = None
    if is_multi:
        steps = [
            PipelineStepState(scenario_id=s.scenario_id, title=s.title, why=s.why)
            for s in plan.steps
        ]
        steps[0].case_id = case_id  # entry-point case runs step 0
        state.pipelines[pipeline_id] = PipelineRecord(
            pipeline_id=pipeline_id,
            prompt=payload.prompt,
            user_id=user.id,
            steps=steps,
            forecast=forecast,
        )
        pipeline_out = PipelineOut(
            pipeline_id=pipeline_id,
            steps=[
                PipelineStepOut(scenario_id=s.scenario_id, title=s.title, why=s.why)
                for s in plan.steps
            ],
            rationale=plan.rationale,
            confidence=plan.confidence,
            forecast=forecast,
        )

    return CreateCaseOut(
        case_id=case_id,
        scenario_id=first_scenario,
        interpreted_as=interpreted_as,
        clarifying_question=clarifying_question,
        confidence=interpreted.confidence,
        candidates=[CandidateOut(**c) for c in candidates_payload],
        pipeline=pipeline_out,
        routing=route,
        rag=rag_answer,
    )


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
    case.scenario_version = sc.get("version") if isinstance(sc.get("version"), int) else None
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
    # Baseline mode auto-defaults to approve (the naive baseline reviewer
    # without governance context is likeliest to greenlight). Forced-
    # decision mode still requires the explicit value.
    if payload.baseline and payload.decision is None:
        decision_value = "approve"
    elif payload.decision in ("approve", "reject", "request_more_info"):
        decision_value = payload.decision
    else:
        raise HTTPException(status_code=400, detail="invalid decision")

    new_id = f"case-{uuid.uuid4().hex[:10]}"
    # Replays run against the LIVE scenario version (not the original
    # case's version), so a replay can exercise the post-edit behaviour.
    # Operators who want to re-run on the exact prior version should
    # rollback the scenario first.
    sc_live = state.scenarios.get(original.scenario_id)
    replay_version = (
        sc_live.get("version") if sc_live and isinstance(sc_live.get("version"), int) else None
    )
    new_case = CaseRecord(
        case_id=new_id,
        prompt=original.prompt,
        scenario_id=original.scenario_id,
        scenario_version=replay_version,
        interpreted_as=original.interpreted_as,
        clarifying_question=None,
        user_id=user.id,
        phase="binding",
        sibling_case_ids=[case_id, *original.sibling_case_ids],
        replay_decision=decision_value,
        baseline=payload.baseline,
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


# =============================================================================
# Compensate — reverse a previously-executed compensatable action.
# =============================================================================
@router.post("/cases/{case_id}/compensate")
async def compensate_case(
    case_id: str, request: Request,
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Fire the compensating side-effect for a previously-executed
    compensatable action on this case. Records the result as an
    `action.compensated` lineage event so the audit trail captures both
    the fire and the rollback as a paired strip.

    Refuses (400) when:
      • the case has no execution_result yet, or it failed,
      • the action isn't compensatable, or has no compensation block,
      • a prior `action.compensated` event already exists (one-shot).
    """
    from tcs_hitl_context import Stage, make_event

    state: AppState = request.app.state.app_state
    case = _own_case_or_403(state, case_id, user)
    er = case.execution_result or {}
    if not er or not er.get("ok"):
        raise HTTPException(
            status_code=400,
            detail="case has no successful execution to compensate",
        )
    action_id = er.get("action_id")
    if not action_id:
        raise HTTPException(
            status_code=400,
            detail="execution_result missing action_id",
        )
    action = state.actions.get(action_id)
    if action is None:
        raise HTTPException(
            status_code=400,
            detail=f"action {action_id!r} not registered",
        )
    if action.reversibility_class != "compensatable" or action.compensation is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"action {action_id!r} is {action.reversibility_class!r}; "
                "no compensation defined"
            ),
        )
    # Idempotency-by-event: if the case already carries an
    # action.compensated event for this action, refuse — the demo's
    # "Compensate" button should only fire once per executed action.
    if case.ctx is not None:
        for ev in case.ctx.lineage:
            if ev.action == "action.compensated":
                raise HTTPException(
                    status_code=400,
                    detail="action already compensated",
                )

    # Build a one-shot Action with the compensation executor swapped in,
    # then dispatch through the same execute_action() path so SQL/HTTP
    # error handling stays uniform with the forward direction.
    from ..actions import execute_action

    compensating_action = action.model_copy(update={"executor": action.compensation})
    args = dict(er.get("args") or {})
    args.setdefault("__case_id", case.case_id)
    result = execute_action(compensating_action, args, sources=state.data_sources)

    # Persist the compensation result on the case so a refresh re-renders
    # the paired strip without re-fetching the lineage table separately.
    case.compensation_result = result.model_dump(mode="json")

    if case.ctx is not None:
        ev = make_event(
            stage=Stage.EXECUTE,
            actor="agent-write-actions",
            action="action.compensated" if result.ok else "action.compensate_failed",
            detail=(
                f"action_id={action_id} · {result.detail}"
                if result.ok
                else f"action_id={action_id} · compensation FAILED: {result.detail}"
            ),
        )
        case.ctx.append_lineage(ev)
        state.lineage.record(case.ctx.case_id, ev)

    state.cases.save(case)
    return {
        "case_id": case_id,
        "action_id": action_id,
        "ok": result.ok,
        "detail": result.detail,
    }


# =============================================================================
# Revise — W1 / Beat 3 ("a decision re-versioned the moment new evidence
# arrived"). Builds a new revision of the case, optionally driven by a
# narrative trigger from the catalog above.
# =============================================================================
@router.get("/cases/{case_id}/revise/triggers")
def list_revise_triggers(
    case_id: str, request: Request,
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Return triggers available for this case's scenario, plus a flag for
    the generic-refresh fallback."""
    state: AppState = request.app.state.app_state
    case = _own_case_or_403(state, case_id, user)
    return {
        "case_id": case_id,
        "scenario_id": case.scenario_id,
        "triggers": _triggers_for_scenario(case.scenario_id),
        "supports_generic_refresh": True,
    }


@router.post("/cases/{case_id}/revise")
async def revise_case(
    case_id: str, payload: ReviseIn, request: Request,
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Seal a new revision of this case driven by `trigger_id`.

    Narrative triggers inject a curated synthetic fact into the target
    stage and re-decide per the trigger's `new_decision`. The "generic
    refresh" path snapshots current state without injection and reports
    no-change in demo mode (the real implementation would re-run the
    proposal + review queries against current data and diff).

    Emits a `case.re_versioned` lineage event with the trigger label so
    the audit trail captures BOTH revisions side-by-side.
    """
    from datetime import datetime, timezone

    from tcs_hitl_context import Stage, make_event

    from ..case_record import CaseRevision
    from ..orchestrator import seal_initial_revision, snapshot_current_stages

    state: AppState = request.app.state.app_state
    case = _own_case_or_403(state, case_id, user)
    # Lazy-seal v1 for cases that completed before W1 shipped (or before
    # the backend was last restarted — revisions live in-memory). A
    # completed case with no revisions is just stale state: snapshot its
    # current stages as v1 so /revise can proceed normally.
    if not case.revisions and case.phase == "complete":
        seal_initial_revision(case)
    if not case.revisions:
        raise HTTPException(
            status_code=400,
            detail="case has no initial revision yet (not completed)",
        )

    last_rev = case.revisions[-1]
    # Generic refresh — actually re-runs the proposal + review binders
    # against current data. If the resulting fact set materially differs
    # from the last revision's snapshot, seal a new revision. Otherwise
    # signal "no change" but the audit trail still records that the
    # check happened.
    if payload.trigger_id == "generic_refresh":
        from ..binders import _facts_from_stage

        if not case.scenario_id:
            raise HTTPException(400, "case has no scenario")
        sc = state.scenarios.get(case.scenario_id)
        if sc is None:
            raise HTTPException(400, f"scenario {case.scenario_id!r} not found")

        # Build the action.payload context the binders need. Mirrors
        # what agent_runtime.draft_action does.
        action_payload = dict(sc.get("action_payload") or {})
        action_payload["__scenario_id__"] = case.scenario_id

        def _kf_to_dict(f):
            return {
                "source": f.ref.source,
                "ontology_type": f.ref.ontology_type,
                "id": f.ref.id,
                "uri": f.ref.uri,
                "title": f.payload.get("title"),
                "summary": f.payload.get("summary"),
                "via_ontology": f.payload.get("via_ontology"),
                "via_source_binding": f.payload.get("via_source_binding"),
                "query_index": f.payload.get("query_index"),
                "hops": f.payload.get("hops"),
                "tier": f.payload.get("tier"),
                "status": f.payload.get("status"),
                "via_path": f.payload.get("via_path"),
                "via_node_id": f.payload.get("via_node_id"),
            }

        stages = sc.get("stages", {})
        fresh_snapshot: list[dict] = []
        # Preserve any inline stages from the last revision (agent_intake's
        # facts come from YAML `facts:` blocks, not data queries — they
        # don't change unless the scenario YAML was edited).
        for stage in last_rev.stages_snapshot:
            if stage["stage"] == "agent_intake":
                fresh_snapshot.append(
                    {**stage, "facts": [{**f} for f in stage.get("facts", [])]}
                )
        # Re-run proposal stage queries
        if "proposal" in stages:
            stage_def = stages["proposal"]
            facts, _ = _facts_from_stage(
                stage_def,
                sources=state.data_sources,
                ontology=state.ontology_resolver,
                payload=action_payload,
            )
            fresh_snapshot.append({
                "stage": "proposal",
                "binder": stage_def.get("binder", "FixtureProposalBinder/1.0"),
                "facts": [_kf_to_dict(f) for f in facts],
            })
        # Re-run review stage queries (if exists)
        if "review" in stages:
            stage_def = stages["review"]
            facts, _ = _facts_from_stage(
                stage_def,
                sources=state.data_sources,
                ontology=state.ontology_resolver,
                payload=action_payload,
            )
            fresh_snapshot.append({
                "stage": "review",
                "binder": stage_def.get("binder", "FixtureReviewBinder/1.0"),
                "facts": [_kf_to_dict(f) for f in facts],
            })

        # Diff fact sets between last revision and fresh snapshot
        def _fact_keys(snapshot: list[dict]) -> set[tuple]:
            out = set()
            for stg in snapshot:
                for f in stg.get("facts", []) or []:
                    out.add((
                        f.get("source"),
                        f.get("ontology_type"),
                        f.get("id"),
                    ))
            return out

        old_keys = _fact_keys(last_rev.stages_snapshot)
        new_keys = _fact_keys(fresh_snapshot)
        material_change = old_keys != new_keys
        total_facts_checked = sum(
            len(s.get("facts") or []) for s in fresh_snapshot
        )

        # Always emit a lineage event so the audit trail records that the
        # check happened — even when nothing materially changed.
        from tcs_hitl_context import Stage, make_event
        if case.ctx is not None:
            ev = make_event(
                stage=Stage.REVIEW,
                actor="agent-revisioning",
                action=(
                    "case.refresh_checked"
                    if not material_change
                    else "case.re_versioned"
                ),
                detail=(
                    f"Re-ran proposal + review binders · {total_facts_checked} "
                    f"facts checked · "
                    + (
                        "no material change · still at v"
                        f"{last_rev.revision_no}"
                        if not material_change
                        else f"changes detected · sealed new revision"
                    )
                ),
            )
            case.ctx.append_lineage(ev)
            state.lineage.record(case.ctx.case_id, ev)

        if not material_change:
            state.cases.save(case)
            return {
                "case_id": case_id,
                "revision_no": last_rev.revision_no,
                "no_change": True,
                "facts_checked": total_facts_checked,
            }

        # Fact set changed — seal new revision. Mark the new-vs-old
        # facts on each fact so the Envelope's green NEW EVIDENCE badge
        # surfaces them.
        for stage in fresh_snapshot:
            for f in stage.get("facts", []):
                key = (f.get("source"), f.get("ontology_type"), f.get("id"))
                if key not in old_keys:
                    f["_revision_new"] = True

        new_revno = last_rev.revision_no + 1
        case.revisions.append(
            CaseRevision(
                revision_no=new_revno,
                stages_snapshot=fresh_snapshot,
                decision=last_rev.decision,
                triggered_by="generic_refresh",
                trigger_label="Re-ran with fresh data",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        case.current_revision = new_revno
        state.cases.save(case)
        return {
            "case_id": case_id,
            "revision_no": new_revno,
            "trigger_label": "Re-ran with fresh data",
            "facts_checked": total_facts_checked,
        }

    trigger = TRIGGER_CATALOG.get(payload.trigger_id)
    if trigger is None:
        raise HTTPException(
            status_code=400,
            detail=f"unknown trigger_id: {payload.trigger_id!r}",
        )

    # Build the new stages snapshot from the previous revision + injection.
    # Deep-copy so we don't mutate the prior snapshot in place.
    new_snapshot = [
        {**stage, "facts": [{**f} for f in stage.get("facts", [])]}
        for stage in (last_rev.stages_snapshot or snapshot_current_stages(case))
    ]
    inject = trigger["inject"]
    target_stage_name = inject["stage"]
    injected_fact = {**inject["fact"]}
    # Mark the fact as new-in-this-revision so the Envelope can render a
    # green gutter on it when v2 (or later) is selected.
    injected_fact["_revision_new"] = True

    for stage in new_snapshot:
        if stage["stage"] == target_stage_name:
            stage["facts"].append(injected_fact)
            break
    else:
        raise HTTPException(
            status_code=500,
            detail=f"target stage {target_stage_name!r} not found in revision",
        )

    new_decision = trigger.get("new_decision", last_rev.decision)
    new_revno = last_rev.revision_no + 1
    case.revisions.append(
        CaseRevision(
            revision_no=new_revno,
            stages_snapshot=new_snapshot,
            decision=new_decision,
            triggered_by=payload.trigger_id,
            trigger_label=trigger["label"],
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    )
    case.current_revision = new_revno

    # Lineage event so the audit trail captures both versions.
    if case.ctx is not None:
        ev = make_event(
            stage=Stage.REVIEW,
            actor="agent-revisioning",
            action="case.re_versioned",
            detail=(
                f"v{new_revno} sealed · trigger: {trigger['label']} · "
                f"new decision: {new_decision}"
            ),
        )
        case.ctx.append_lineage(ev)
        state.lineage.record(case.ctx.case_id, ev)

    state.cases.save(case)
    return {
        "case_id": case_id,
        "revision_no": new_revno,
        "trigger_label": trigger["label"],
        "new_decision": new_decision,
    }


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


@router.get("/cases/{case_id}/highlights")
async def case_highlights(
    case_id: str, request: Request, user: CurrentUser = Depends(current_user)
) -> dict:
    """Phase 2 — the load-bearing facts the reviewer flagged.

    Read-back of the denormalised `case_highlighted_facts` rows for a
    case. Empty list when the reviewer didn't flag anything, when the
    case is autonomous (no reviewer), or when the case predates Phase 2.
    """
    state: AppState = request.app.state.app_state
    case = _own_case_or_403(state, case_id, user)
    rows: list[dict] = []
    if hasattr(state.cases, "read_highlighted_facts"):
        rows = state.cases.read_highlighted_facts(case_id)
    return {
        "case_id": case.case_id,
        "scenario_id": case.scenario_id,
        "scenario_version": case.scenario_version,
        "decision_kind": case.decision_kind,
        "highlighted_fact_refs": rows,
    }


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
        "scenario_version": c.scenario_version,
        "phase": c.phase,
        "decision_kind": c.decision_kind,
        "interpreted_as": c.interpreted_as,
        "clarifying_question": c.clarifying_question,
        "confidence": c.confidence,
        "candidates": c.candidates,
        "sibling_case_ids": c.sibling_case_ids,
        "replay_decision": c.replay_decision,
        "baseline": c.baseline,
    }


def _case_full(state: AppState, c: CaseRecord) -> dict:
    out = _case_summary(c)
    out["stages"] = []
    out["lineage"] = []
    out["closing_message"] = c.closing_message
    out["execution_result"] = c.execution_result
    out["compensation_result"] = c.compensation_result
    out["risk_band"] = c.risk_band
    out["revisions"] = [
        {
            "revision_no": r.revision_no,
            "stages_snapshot": r.stages_snapshot,
            "decision": r.decision,
            "triggered_by": r.triggered_by,
            "trigger_label": r.trigger_label,
            "created_at": r.created_at,
        }
        for r in c.revisions
    ]
    out["current_revision"] = c.current_revision
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
            # The write-action target the orchestrator will dispatch on
            # approve (HITL) or directly (autonomous). Exposed so the UI
            # can render an "If you approve, this is what runs" preview
            # alongside the bound facts — and so it can highlight the
            # specific evidence card (e.g. matching FreightRate) that
            # corresponds to the chosen values.
            "executor": scenario.get("_executor"),
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
                        # query_index correlates this fact back to the
                        # KnowledgeQuery that produced it (None for inline
                        # `facts:` blocks). Used by the frontend's
                        # QueryPlanPanel for click-to-highlight.
                        "query_index": f.payload.get("query_index"),
                        # Structured multi-hop depth markers (set by graph
                        # resolvers when the cypher RETURNs `hops` / `tier`
                        # columns). Drive the "hidden dependency" callout in
                        # the Envelope without parsing summary text.
                        "hops": f.payload.get("hops"),
                        "tier": f.payload.get("tier"),
                        # Role + path markers (also set by graph resolvers).
                        # `status` drives the FAILING pill on Supplier facts
                        # whose underlying node has e.g. `chapter_11_filed_*`.
                        # `via_path` is a human label for the relationship
                        # vector that connects the case subject to the fact's
                        # entity. `via_node_id` is the intermediate graph
                        # node (e.g. the HoldingCompany) used to highlight
                        # the chain inside GraphViz.
                        "status": f.payload.get("status"),
                        "via_path": f.payload.get("via_path"),
                        "via_node_id": f.payload.get("via_node_id"),
                    }
                    for f in sc.facts
                ],
                # Per-stage queries — what the agent ACTUALLY asked the
                # ontology resolver for. Synthetic placeholder queries that
                # the agent_intake binder records purely for audit-trail
                # completeness (when a stage uses only inline `facts:` and
                # ran no real ontology queries) are filtered out here so the
                # frontend's "Why these cards?" panel only shows real lookups.
                # The marker is the `__ontology__` filter key — present on
                # every query that came from a scenario's ontology_queries
                # block, absent on the synthetic placeholders.
                "queries": [
                    {
                        "index": idx,
                        "ontology_type": q.ontology_type,
                        "ontology": q.filters.get("__ontology__"),
                        "where": {
                            k: v for k, v in q.filters.items()
                            if k != "__ontology__"
                        },
                        "purpose": q.purpose,
                        "max_results": q.max_results,
                        "fact_count": sum(
                            1 for f in sc.facts
                            if f.payload.get("query_index") == idx
                        ),
                    }
                    for idx, q in enumerate(sc.queries_issued)
                    if q.filters.get("__ontology__") is not None
                ],
            }
            for stage, sc in c.ctx.stages.items()
        ]
        out["lineage"] = [ev.model_dump(mode="json") for ev in c.ctx.lineage]
    # Phase 3b — match the case's bound facts against any
    # `auto_promoted_patterns` the scenario carries. The UI shows
    # these as advisory chips ("In 8 of 8 similar SC-PP-008 cases,
    # reviewers rejected for SanctionsProximity"). Empty list when
    # the scenario has no promoted patterns or none of them fire on
    # this case's facts.
    out["matched_promoted_patterns"] = _matched_promoted_patterns(scenario, out["stages"])
    return out


def _matched_promoted_patterns(
    scenario: Optional[dict], stages: list[dict]
) -> list[dict]:
    """Walk every promoted pattern on the scenario; for each, count
    how many bound facts match its trigger; if the count meets
    `trigger.min_facts`, return the pattern annotated with the count
    and a hint of which facts matched."""
    if not scenario:
        return []
    patterns = scenario.get("auto_promoted_patterns") or []
    if not patterns:
        return []
    # Flatten facts across stages and index by ontology_type for cheap lookup.
    by_ontology_type: dict[str, list[dict]] = {}
    for s in stages:
        for f in s.get("facts") or []:
            ot = f.get("ontology_type")
            if ot:
                by_ontology_type.setdefault(ot, []).append(f)
    matched: list[dict] = []
    for p in patterns:
        trig = p.get("trigger") or {}
        ot = trig.get("ontology_type")
        min_facts = int(trig.get("min_facts") or 1)
        hits = by_ontology_type.get(ot or "", [])
        if len(hits) >= min_facts:
            matched.append({
                "id": p.get("id"),
                "decision_kind": p.get("decision_kind"),
                "suggested_rationale": p.get("suggested_rationale"),
                "trigger": trig,
                "metadata": p.get("metadata") or {},
                "matched_fact_count": len(hits),
                "matched_fact_ids": [h.get("id") for h in hits[:3]],
            })
    return matched
