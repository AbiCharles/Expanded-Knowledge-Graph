"""Run a multi-scenario pipeline as real, chained HITL cases (Phase 2).

Each step runs through the existing single-case orchestrator (`run_case`),
which binds the stages and — for a HITL step — blocks on the reviewer's
decision. When a step resolves with a *continue* decision (approve /
auto_execute) the next step launches; any other decision (reject /
request_more_info / an autonomy escalation that gets rejected) ends the
pipeline. The reviewer reviews each step through the exact same UI as a
standalone case.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from . import orchestrator
from .case_record import CaseRecord
from .pipeline import PipelineRecord
from .probability import CONTINUE_KINDS

log = logging.getLogger(__name__)

# How long to wait for a step to reach review_ready before giving up (seconds).
_STEP_TIMEOUT = 60.0


def _new_step_case(state, pipeline: PipelineRecord, step_index: int) -> CaseRecord:
    """Create (and register) the case for a downstream pipeline step."""
    step = pipeline.steps[step_index]
    sc = state.scenarios.get(step.scenario_id) or {}
    version = sc.get("version") if isinstance(sc.get("version"), int) else None
    case = CaseRecord(
        case_id=f"case-{uuid.uuid4().hex[:10]}",
        prompt=pipeline.prompt,
        scenario_id=step.scenario_id,
        scenario_version=version,
        interpreted_as=sc.get("interpreted_as", ""),
        clarifying_question=sc.get("clarifying_question", ""),
        user_id=pipeline.user_id,
        phase="binding",
        pipeline_id=pipeline.pipeline_id,
        pipeline_step=step_index,
    )
    state.cases[case.case_id] = case
    return case


async def run_pipeline(state, pipeline: PipelineRecord) -> None:
    """Execute the pipeline's steps in order, chaining on continue-decisions.

    Step 0's case is created up front (by create_case); later steps are
    created lazily here. Blocks per step on `run_case` — which returns once
    the step's decision has been recorded and finalised — then reads
    `case.decision_kind` to decide whether to advance.
    """
    pipeline.status = "running"
    n = len(pipeline.steps)
    try:
        for i in range(n):
            pipeline.current_step = i
            step = pipeline.steps[i]
            case = state.cases.get(step.case_id) if step.case_id else None
            if case is None:
                case = _new_step_case(state, pipeline, i)
                step.case_id = case.case_id

            if case.decision_kind:
                # Already resolved — e.g. the operator ran the entry-point
                # case via the normal Confirm before hitting "Run pipeline".
                # Reuse its decision instead of double-running the step.
                decision = case.decision_kind
            else:
                # Runs the step to completion (HITL blocks on the reviewer's
                # decision; autonomous steps auto-execute) and returns.
                await orchestrator.run_case(state, case)
                decision = case.decision_kind or "no_op"
            step.decision = decision

            # Stop unless the decision lets the workflow proceed to a next step.
            if decision not in CONTINUE_KINDS or i == n - 1:
                pipeline.terminal_decision = decision
                break
        pipeline.status = "complete"
    except Exception as exc:  # noqa: BLE001 — never let a step kill the loop silently
        log.exception("pipeline %s failed at step %s", pipeline.pipeline_id, pipeline.current_step)
        pipeline.status = "error"
        pipeline.error = str(exc)


async def run_pipeline_path(state, pipeline: PipelineRecord, prescribed: dict[str, str]) -> None:
    """Execute an approved pathway end-to-end, auto-applying its decisions.

    The reviewer approved one whole pathway, so instead of blocking on a human
    at each HITL step we auto-file the decision that pathway prescribes for
    each scenario (defaulting to "approve" for any step the path doesn't name),
    which lets the normal executor fire. Autonomous steps that don't escalate
    just auto-execute. Stops if a prescribed decision doesn't continue.
    """
    from .api.decisions import record_decision_internal  # lazy: avoid import cycle

    pipeline.status = "running"
    n = len(pipeline.steps)
    try:
        for i in range(n):
            pipeline.current_step = i
            step = pipeline.steps[i]
            case = state.cases.get(step.case_id) if step.case_id else None
            if case is None:
                case = _new_step_case(state, pipeline, i)
                step.case_id = case.case_id

            if case.decision_kind:
                decision = case.decision_kind
            else:
                task = asyncio.create_task(orchestrator.run_case(state, case))
                waited = 0.0
                while not task.done():
                    if case.phase == "review_ready" and case.ticket_id and not case.decision_kind:
                        want = prescribed.get(step.scenario_id, "approve")
                        await record_decision_internal(
                            state=state, case=case, decision=want,
                            reviewer_id="pathway-auto",
                            rationale="Auto-applied from the approved pathway.",
                            follow_up=None,
                        )
                        break
                    await asyncio.sleep(0.05)
                    waited += 0.05
                    if waited > _STEP_TIMEOUT:
                        break
                await task
                decision = case.decision_kind or "no_op"

            step.decision = decision
            if decision not in CONTINUE_KINDS or i == n - 1:
                pipeline.terminal_decision = decision
                break
        pipeline.status = "complete"
    except Exception as exc:  # noqa: BLE001
        log.exception("pipeline %s (path) failed at step %s", pipeline.pipeline_id, pipeline.current_step)
        pipeline.status = "error"
        pipeline.error = str(exc)
