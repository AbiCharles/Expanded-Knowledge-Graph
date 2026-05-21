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
        state.cases.save(case)
        await state.bus.close(case.case_id)
        return

    scenario = state.scenarios.require(case.scenario_id)

    # Stage 1 — agent intake binding
    case.phase = "binding"
    state.cases.save(case)
    ctx = state.service.open_case(
        agent_id=scenario["actor_id"],
        scenario={"scenario_id": case.scenario_id, "domain": scenario["domain"]},
        transport_mode=TransportMode.ASYNC,
    )
    case.ctx = ctx
    case.framework_case_id = ctx.case_id
    state.cases.save(case)
    await state.bus.emit(case.case_id, _stage_event(ctx, Stage.AGENT_INTAKE))

    await asyncio.sleep(DELAY_BETWEEN_STAGES)

    # Stage 2 — proposal binding
    action = state.agent_runtime.draft_action(scenario)
    # Phase 3.E enhancement: when a chip-style ontology lookup scenario
    # routes a prompt that mentions a filter (e.g. *"show me Dutch
    # suppliers"* hits SC-ONTO-supply_chain-Supplier), pre-parse the
    # prompt against the bound ontology and stash the extracted where on
    # the action so the binder can merge it into the ontology_query's
    # `where: {}`. Only fires when the scenario marks itself
    # `_filter_from_prompt: true` — keeps hand-authored scenarios with
    # deliberate empty/literal where clauses untouched.
    if scenario.get("_filter_from_prompt") and (case.prompt or "").strip():
        try:
            prompt_filters = await _extract_prompt_filters(
                state, scenario, case.prompt
            )
        except Exception as exc:  # noqa: BLE001
            log.info("prompt-filter extraction skipped: %s", exc)
            prompt_filters = {}
        if prompt_filters:
            action.payload["__prompt_filters__"] = prompt_filters
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
    state.cases.save(case)
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

    # If the scenario wires an `_executor` block, run the action on
    # approve. Result is stashed on the case so the detail endpoint and
    # the audit trail both surface it.
    if rd.decision.value == "approve":
        _maybe_run_executor(state, case, scenario)

    state.cases.save(case)

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

    # Autonomous scenarios that wire an `_executor` block run here too.
    _maybe_run_executor(state, case, scenario)

    state.cases.save(case)

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


async def _extract_prompt_filters(
    state: AppState, scenario: dict, prompt: str
) -> dict[str, dict]:
    """Parse the prompt against every ontology referenced by the
    scenario's `ontology_queries:` blocks and return the per-target
    where dict.

    Returned shape: `{f"{ontology_id}.{class}": where_dict}`. The binder
    uses the same key to look up filters when issuing a query, so a
    prompt-extracted `country: NL` only ends up applied to a query that
    targets the same class the parser identified.
    """
    from .ontology import (
        NLParseError,
        collect_attribute_samples,
        parse_nl_query,
    )

    proposal = (scenario.get("stages") or {}).get("proposal") or {}
    queries = proposal.get("ontology_queries") or []
    if not queries:
        return {}

    out: dict[str, dict] = {}
    # Group by ontology so we only hit the parser once per ontology, not
    # once per ontology_query.
    ontology_ids = {q.get("ontology") for q in queries if q.get("ontology")}
    for ontology_id in ontology_ids:
        onto = state.ontologies.get(ontology_id)
        if onto is None:
            continue
        mapping = state.ontologies.get_mapping(ontology_id)
        samples = collect_attribute_samples(onto, mapping, state.data_sources)
        try:
            parsed = await parse_nl_query(
                prompt, onto, state.llm, attribute_samples=samples
            )
        except NLParseError:
            continue
        if parsed.where:
            out[f"{ontology_id}.{parsed.class_}"] = dict(parsed.where)
    return out


def _maybe_run_executor(state: AppState, case: CaseRecord, scenario: dict) -> None:
    """If the scenario carries an `_executor` block, look up the action,
    invoke it, and record the outcome.

    Hand-authored scenarios opt in by adding an `_executor: {action_id,
    arguments}` block. The orchestrator dispatches the named action's
    executor (sql_update / http_request) on autonomous or post-approval
    paths. No-op for any scenario that doesn't carry an `_executor` block.

    Failures don't raise — they're captured into `case.execution_result`
    so the audit trail tells the truth and the case completion path
    continues.
    """
    executor_cfg = scenario.get("_executor")
    if not executor_cfg:
        return
    action_id = executor_cfg.get("action_id")
    arguments = executor_cfg.get("arguments") or {}
    if not action_id:
        log.warning("scenario %s has _executor but no action_id", scenario.get("id"))
        return
    action = state.actions.get(action_id)
    if action is None:
        case.execution_result = {
            "action_id": action_id,
            "ok": False,
            "detail": f"action {action_id!r} no longer registered",
            "args": arguments,
        }
        return
    from .actions import execute_action

    result = execute_action(action, arguments, sources=state.data_sources)
    case.execution_result = result.model_dump(mode="json")

    # Append a lineage event so the audit trail captures the executor run.
    if case.ctx is not None:
        ev = make_event(
            stage=Stage.EXECUTE,
            actor=scenario.get("actor_id") or "agent-write-actions",
            action="executed" if result.ok else "executor_failed",
            detail=result.detail,
        )
        case.ctx.append_lineage(ev)
        state.lineage.record(case.ctx.case_id, ev)


def _closing_message_for(scenario: dict, case: CaseRecord) -> Optional[str]:
    template = (
        scenario.get("closing_messages", {})
        .get(case.decision_kind or "", "")
    )
    if not template:
        return None
    return template.replace("{rationale}", case.rationale or "")
