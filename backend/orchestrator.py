"""Case orchestrator — drives a single case through the four stages.

Threads the framework's sync `HITLContextService` calls into the FastAPI async
event loop, emitting SSE events between stages so the UI can render the envelope
filling up in real time.

The orchestrator is invoked from POST /api/cases/{case_id}/confirm and from
POST /api/cases/{case_id}/replay; both spawn the same coroutine.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from tcs_hitl_context import (
    KnowledgeContext,
    Stage,
    TransportMode,
    make_event,
)

from . import policy
from .sse import CaseEvent
from .state import AppState, CaseRecord

log = logging.getLogger(__name__)


# Pacing — gives the UI time to render each transition. Mirrors the JS demo timings.
DELAY_BETWEEN_STAGES = 0.9
DELAY_BEFORE_AUTO_APPROVE = 0.9


async def run_case(state: AppState, case: CaseRecord) -> None:
    """Run the full pipeline for a confirmed case."""
    if not case.scenario_id:
        log.warning("case %s has no scenario_id; aborting", case.case_id)
        case.phase = "cancelled"
        await state.bus.close(case.case_id)
        return

    scenario = state.scenarios.require(case.scenario_id)

    # Stage 1 — agent intake binding
    case.phase = "binding"
    ctx = state.service.open_case(
        agent_id=scenario["actor_id"],
        scenario={"scenario_id": case.scenario_id, "domain": scenario["domain"]},
        transport_mode=TransportMode.ASYNC,
    )
    case.ctx = ctx
    await state.bus.emit(case.case_id, _stage_event(ctx, Stage.AGENT_INTAKE))

    await asyncio.sleep(DELAY_BETWEEN_STAGES)

    # Stage 2 — proposal binding
    action = state.agent_runtime.draft_action(scenario)
    state.service.attach_proposal(ctx, action)
    await state.bus.emit(case.case_id, _stage_event(ctx, Stage.PROPOSAL))

    # Branch — autonomous vs HITL
    decision = policy.evaluate(scenario)
    if decision.mode == "auto_approve":
        await asyncio.sleep(DELAY_BEFORE_AUTO_APPROVE)
        await _finalise_autonomous(state, case, decision)
        return

    # HITL path
    await asyncio.sleep(DELAY_BETWEEN_STAGES)

    # Stage 3 — review binding + submit. The framework's submit_for_review is
    # synchronous (writes to the in-memory queue, returns a ticket).
    ticket = state.service.submit_for_review(ctx)
    case.ticket_id = ticket.ticket_id
    case.phase = "review_ready"
    case.decision_event = asyncio.Event()
    await state.bus.emit(
        case.case_id,
        CaseEvent(
            kind="review_ready",
            data={
                "case_id": case.case_id,
                "ticket_id": ticket.ticket_id,
                "stage": _stage_payload(ctx, Stage.REVIEW),
                "rendered_card": state.surface.render(ctx),
            },
        ),
    )

    # Wait for the decision endpoint to write into the decision store and set
    # our event. We don't time out — production would.
    await case.decision_event.wait()

    rd = state.service.collect_decision(ctx, ticket.ticket_id)
    if rd is None:
        log.error("decision_event was set but transport.poll returned None")
        return

    case.phase = "complete"
    case.decision_kind = rd.decision.value
    case.rationale = rd.rationale or None
    case.closing_message = _closing_message_for(scenario, case)

    await state.bus.emit(
        case.case_id,
        CaseEvent(
            kind="decided",
            data={
                "case_id": case.case_id,
                "decision": rd.decision.value,
                "rationale": rd.rationale,
                "reviewer_id": rd.reviewer_id,
                "follow_up": case.follow_up,
                "outcome": scenario.get("outcomes", {}).get(rd.decision.value, {}),
                "closing_message": case.closing_message,
                "lineage": [ev.model_dump(mode="json") for ev in ctx.lineage],
            },
        ),
    )
    await state.bus.close(case.case_id)


async def _finalise_autonomous(state: AppState, case: CaseRecord, pd: policy.PolicyDecision) -> None:
    """Auto-execute path. Records a synthetic lineage event and finalises."""
    assert case.ctx is not None
    scenario = state.scenarios.require(case.scenario_id)  # type: ignore[arg-type]

    ev = make_event(
        stage=Stage.EXECUTE,
        actor=scenario["actor_id"],
        action="auto-approved",
        detail=f"{pd.guardrail_id} cleared this action — no human review required",
    )
    case.ctx.append_lineage(ev)
    state.lineage.record(case.ctx.case_id, ev)

    case.phase = "complete"
    case.decision_kind = "auto_execute"
    case.closing_message = scenario.get("closing_message", "")

    await state.bus.emit(
        case.case_id,
        CaseEvent(
            kind="auto_approved",
            data={
                "case_id": case.case_id,
                "guardrail_id": pd.guardrail_id,
                "reason": pd.reason,
                "outcome": scenario.get("outcomes", {}).get("auto_execute", {}),
                "closing_message": case.closing_message,
                "lineage": [ev.model_dump(mode="json") for ev in case.ctx.lineage],
            },
        ),
    )
    await state.bus.close(case.case_id)


# =============================================================================
# Helpers
# =============================================================================
def _stage_event(ctx: KnowledgeContext, stage: Stage) -> CaseEvent:
    return CaseEvent(
        kind="stage_bound",
        data={
            "case_id": ctx.case_id,
            "stage": _stage_payload(ctx, stage),
            "lineage": [ev.model_dump(mode="json") for ev in ctx.lineage],
        },
    )


def _stage_payload(ctx: KnowledgeContext, stage: Stage) -> dict:
    sc = ctx.stages.get(stage)
    if sc is None:
        return {}
    return {
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
            }
            for f in sc.facts
        ],
    }


def _closing_message_for(scenario: dict, case: CaseRecord) -> Optional[str]:
    template = (
        scenario.get("closing_messages", {})
        .get(case.decision_kind or "", "")
    )
    if not template:
        return None
    return template.replace("{rationale}", case.rationale or "")
