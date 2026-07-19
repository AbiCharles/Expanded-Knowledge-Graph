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
from .case_record import CaseRevision
from .risk_band import evaluate_risk_band
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

    # Stage 2 — proposal binding. Baseline replays (case.baseline=True)
    # are signalled to the binder via the __baseline__ payload key so the
    # review-stage binder can short-circuit its ontology queries.
    action = state.agent_runtime.draft_action(scenario, baseline=case.baseline)
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
            # Also overlay extracted keys onto the action payload so any
            # `:payload-ref` substitution in OTHER ontology_queries (queries
            # against a different class than the one the parser identified)
            # picks up the same filter value. Without this, two queries that
            # share a key (e.g. carrier dashboard binding both Carrier and
            # Shipment by carrier_id) end up inconsistent: the parsed class
            # gets the prompt value, the other gets the hardcoded default.
            for where in prompt_filters.values():
                for k, v in where.items():
                    if v is None:
                        continue
                    action.payload[k] = v
    state.service.attach_proposal(ctx, action)
    # RCA synthesis — if the proposal stage declares a `synthesis:` block,
    # run the LLM inference pass (5-Why) over the just-bound evidence and
    # append the reasoning as synthesized facts BEFORE we emit the proposal
    # envelope, so the reviewer sees the chain alongside its evidence.
    # Additive: no-op for scenarios without a `synthesis:` block.
    await _maybe_run_synthesis(state, ctx, scenario, action)
    await state.bus.emit(case.case_id, _stage_event(ctx, Stage.PROPOSAL))

    # Idempotency check — runs the action's predicate_sql against the target
    # source. If current state already matches what the action would write,
    # short-circuit the entire decision/execute path so the reviewer never
    # sees a misleading 'before→after' diff with the same values on both
    # sides. Quiet no-op for HITL + autonomous alike.
    no_op = _check_idempotency(state, case, scenario)
    if no_op is not None:
        await _finalise_no_op(state, case, scenario, no_op)
        return

    # W4 / Beat 5 — dynamic authority recalculation. Before the
    # autonomy branch picks a path, evaluate the scenario's optional
    # risk-band block against the drafted action's payload. If a band
    # matches with escalate_to=review_ready, override autonomy: emit an
    # `authority.recalculated` lineage event and fall through to the
    # HITL path below. Non-autonomous scenarios still see the lineage
    # event when a band matches, but the path is unchanged (already HITL).
    risk_match = evaluate_risk_band(scenario, action.payload)
    is_autonomous = bool(scenario.get("autonomous"))
    will_escalate = (
        risk_match is not None
        and risk_match.get("escalate_to") == "review_ready"
        and is_autonomous
    )
    if risk_match is not None:
        case.risk_band = {
            "band": risk_match["band"],
            "matched_field": risk_match.get("matched_field"),
            "matched_value": risk_match.get("matched_value"),
            "threshold": risk_match.get("threshold"),
            "op": risk_match.get("op"),
            "escalated": will_escalate,
            "reason": risk_match.get("reason"),
        }
    if will_escalate:
        ev = make_event(
            stage=Stage.PROPOSAL,
            actor="agent-authority-router",
            action="authority.recalculated",
            detail=(
                f"Autonomy demoted · band: {risk_match['band']} · "
                f"{risk_match.get('matched_field')}={risk_match.get('matched_value')} "
                f"{risk_match.get('op')} {risk_match.get('threshold')} · "
                f"escalated from auto_execute to review_ready"
            ),
        )
        ctx.append_lineage(ev)
        state.lineage.record(ctx.case_id, ev)

    # Branch — autonomous vs HITL. If risk_band escalated above, treat
    # this case as HITL even though the scenario is declared autonomous.
    decision = policy.evaluate(scenario)
    if decision.mode == "auto_approve" and not will_escalate:
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

    # W1 / Beat 3 — seal v1 of the revision history before persisting so
    # the Envelope's revision selector always has at least one entry.
    seal_initial_revision(case)

    state.cases.save(case)
    # Phase 2 — mirror the reviewer's load-bearing-fact picks into the
    # denormalised mining table. The list lives on `case.highlighted_fact_refs`
    # already (decisions.record_decision_internal stashed it before
    # unblocking us); this just keeps the queryable copy in sync.
    if hasattr(state.cases, "write_highlighted_facts"):
        state.cases.write_highlighted_facts(case)

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

    # Autonomous scenarios don't pause for a human, but still bind + surface the
    # review-stage evidence (e.g. CAPA candidates + prior CAPAs) so the completed
    # case presents the FULL evidence package as its outcome — the same rich view
    # a reviewer would see, just auto-decided.
    ctx = case.ctx
    if ctx.action is not None and "review" in (scenario.get("stages") or {}):
        try:
            review = state.service.review_binder.bind(ctx.action, ctx)
            ctx.attach_stage(review)
            rev_ev = make_event(
                stage=Stage.REVIEW,
                actor="hitl_service",
                action="auto_bound",
                detail=f"review evidence bound autonomously — {len(review.facts)} fact(s)",
            )
            ctx.append_lineage(rev_ev)
            state.lineage.record(ctx.case_id, rev_ev)
        except Exception:  # noqa: BLE001
            log.exception("autonomous review binding failed; continuing")

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
    seal_initial_revision(case)

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


async def _maybe_run_synthesis(
    state: AppState, ctx: KnowledgeContext, scenario: dict, action
) -> None:
    """Run the RCA reasoning pass(es) over the bound proposal evidence.

    Opt-in: a scenario's `stages.proposal.synthesis` selects the mode(s) —
    ``all`` (every registered method), a single mode string, or a list.
    Each mode reasons over the SAME original evidence snapshot; its facts are
    appended to the proposal StageContext (so they ride along in the envelope,
    the SSE payload, and the revision snapshot) and a lineage event records the
    result. Never raises — synthesis is best-effort enrichment and must not
    sink the case.
    """
    proposal_def = (scenario.get("stages") or {}).get("proposal") or {}
    from .rca_synthesis import resolve_modes, run_synthesis_modes

    modes = resolve_modes(proposal_def.get("synthesis"))
    if not modes:
        return
    stage_ctx = ctx.stages.get(Stage.PROPOSAL)
    if stage_ctx is None:
        return
    try:
        results = await run_synthesis_modes(
            state.llm, modes,
            evidence_facts=stage_ctx.facts, payload=dict(action.payload),
        )
        actor = scenario.get("actor_id") or "agent-rca-synthesis"
        for mode, facts, detail in results:
            stage_ctx.facts.extend(facts)
            ev = make_event(
                stage=Stage.PROPOSAL,
                actor=actor,
                action=f"synthesis.{mode}",
                detail=f"{mode} synthesis → {detail}",
            )
            ctx.append_lineage(ev)
            state.lineage.record(ctx.case_id, ev)
    except Exception:  # noqa: BLE001
        log.exception("RCA synthesis pass failed; proposal continues without it")


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
    # W5 / Beat 2 — baseline replays may carry a `_baseline_executor`
    # block that fires a DIFFERENT executor (or, more commonly, the same
    # action with a different alternate supplier) so the comparison
    # modal can lead with a concrete contrast: "harness picked Ironcrest,
    # baseline picked Stillwater — same parent, lapsed qualification."
    # Falls back to `_executor` when the baseline-specific block isn't
    # defined, so scenarios that don't opt in still work unchanged.
    executor_cfg = (
        scenario.get("_baseline_executor")
        if case.baseline and scenario.get("_baseline_executor")
        else scenario.get("_executor")
    )
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

    # Inject runtime context the action can reference from its SQL (e.g.
    # `:__case_id` in a history-table INSERT) without the scenario author
    # having to hardcode it. Underscore-prefixed keys signal "framework
    # injected, not scenario authored."
    runtime_args = dict(arguments)
    runtime_args.setdefault("__case_id", case.case_id)
    result = execute_action(action, runtime_args, sources=state.data_sources)
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


# =============================================================================
# W1 / Beat 3 — case revisioning helpers
# =============================================================================
def snapshot_current_stages(case: CaseRecord) -> list[dict]:
    """Serialize the case's current ctx.stages into JSON-ready dicts.

    Shape mirrors what `/api/cases/{id}` already produces for `stages`, so
    the frontend can render any revision's snapshot using the same Envelope
    code path it uses for the live state.
    """
    if case.ctx is None:
        return []
    out: list[dict] = []
    for stage, sc in case.ctx.stages.items():
        out.append({
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
                    "query_index": f.payload.get("query_index"),
                    "hops": f.payload.get("hops"),
                    "tier": f.payload.get("tier"),
                    "status": f.payload.get("status"),
                    "via_path": f.payload.get("via_path"),
                    "via_node_id": f.payload.get("via_node_id"),
                }
                for f in sc.facts
            ],
        })
    return out


def seal_initial_revision(case: CaseRecord) -> None:
    """Seal v1 once the initial decision has landed.

    Idempotent — only seals when revisions[] is empty. Called by every
    completion path (HITL decision, autonomous, no-op) so any case that
    finishes has at least one revision to point at."""
    if case.revisions:
        return
    from datetime import datetime, timezone
    case.revisions.append(
        CaseRevision(
            revision_no=1,
            stages_snapshot=snapshot_current_stages(case),
            decision=case.decision_kind,
            triggered_by="initial",
            trigger_label="Initial decision",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    )
    case.current_revision = 1


def _closing_message_for(scenario: dict, case: CaseRecord) -> Optional[str]:
    template = (
        scenario.get("closing_messages", {})
        .get(case.decision_kind or "", "")
    )
    if not template:
        return None
    return template.replace("{rationale}", case.rationale or "")


def _check_idempotency(
    state: AppState, case: CaseRecord, scenario: dict
) -> Optional[dict]:
    """If the scenario wires a write action that declares an idempotency
    block, probe the target source to see if the action would be a no-op.

    Returns a dict describing the no-op outcome (action_id, args, message,
    description) when the predicate matches; ``None`` otherwise (action
    should proceed normally).
    """
    executor_cfg = scenario.get("_executor")
    if not executor_cfg:
        return None
    action_id = executor_cfg.get("action_id")
    if not action_id:
        return None
    action = state.actions.get(action_id)
    if action is None or action.idempotency is None:
        return None

    arguments = executor_cfg.get("arguments") or {}
    idem = action.idempotency
    source = state.data_sources.get(idem.data_source)
    if source is None:
        log.warning(
            "idempotency check for %s skipped: data_source %r not registered",
            action_id, idem.data_source,
        )
        return None
    # Only SQLite/Postgres-like sources expose `run_query`. HTTP / CSV /
    # vector idempotency would need a different probe path — out of scope
    # for now.
    runner = getattr(source, "run_query", None)
    if runner is None:
        log.warning(
            "idempotency check for %s skipped: source %r does not support run_query",
            action_id, idem.data_source,
        )
        return None
    result = runner(idem.predicate_sql, arguments, limit=1)
    if "error" in result:
        log.warning(
            "idempotency check for %s errored — proceeding with executor: %s",
            action_id, result["error"],
        )
        return None
    if not result.get("rows"):
        return None  # predicate matched zero rows → not a no-op

    try:
        message = idem.no_op_message.format(**arguments)
    except (KeyError, IndexError):
        message = idem.no_op_message
    return {
        "action_id": action_id,
        "args": arguments,
        "message": message,
        "description": idem.description or "",
    }


async def _finalise_no_op(
    state: AppState, case: CaseRecord, scenario: dict, no_op: dict
) -> None:
    """Complete a case as a no-op without invoking the executor or routing
    to a reviewer. Mirrors the autonomous-complete shape so the frontend
    can reuse the same chat-thread terminal rendering."""
    assert case.ctx is not None
    # Lineage event so the audit trail records the short-circuit.
    ev = make_event(
        stage=Stage.EXECUTE,
        actor=scenario.get("actor_id") or "agent-write-actions",
        action="skipped_no_op",
        detail=no_op["message"],
    )
    case.ctx.append_lineage(ev)
    state.lineage.record(case.ctx.case_id, ev)

    case.phase = "complete"
    case.decision_kind = "no_op"
    case.closing_message = no_op["message"]
    case.execution_result = {
        "action_id": no_op["action_id"],
        "ok": True,
        "was_noop": True,
        "detail": no_op["message"],
        "args": no_op["args"],
    }
    seal_initial_revision(case)
    state.cases.save(case)

    await state.bus.emit(
        case.case_id,
        CaseEvent(
            kind="decided",
            data={
                "case_id": case.case_id,
                "decision": "no_op",
                "rationale": no_op.get("description") or "",
                "reviewer_id": None,
                "follow_up": None,
                "outcome": {
                    "headline": "No change needed",
                    "detail": no_op["message"],
                },
                "closing_message": case.closing_message,
                "lineage": [ev.model_dump(mode="json") for ev in case.ctx.lineage],
            },
        ),
    )
    await state.bus.close(case.case_id)
