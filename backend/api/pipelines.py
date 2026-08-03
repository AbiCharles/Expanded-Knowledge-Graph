"""Multi-scenario pipeline endpoints (Phase 2).

A pipeline is created by POST /cases when a question spans 2+ scenarios.
`confirm` kicks off the real chained HITL execution; `GET` returns live
state (status, current step, per-step decisions, the actual path taken, and
the probability forecast) so the UI can overlay progress onto the graph.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import pipeline_orchestrator
from ..auth import CurrentUser, current_user
from ..pipeline import prescribed_for_path
from ..state import AppState

log = logging.getLogger(__name__)

router = APIRouter(tags=["pipelines"], prefix="/pipelines")


def _own_pipeline_or_403(state: AppState, pipeline_id: str, user: CurrentUser):
    pipeline = state.pipelines.get(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="pipeline not found")
    if user.role != "admin" and pipeline.user_id is not None and pipeline.user_id != user.id:
        raise HTTPException(status_code=403, detail="not your pipeline")
    return pipeline


@router.get("/{pipeline_id}")
def get_pipeline(
    pipeline_id: str, request: Request, user: CurrentUser = Depends(current_user)
) -> dict:
    """Live pipeline state, including the actual path taken so far."""
    state: AppState = request.app.state.app_state
    return _own_pipeline_or_403(state, pipeline_id, user).public_dict()


@router.post("/{pipeline_id}/confirm")
async def confirm_pipeline(
    pipeline_id: str, request: Request, user: CurrentUser = Depends(current_user)
) -> dict:
    """Start step-by-step chained execution as a background task.

    (Legacy per-step-review flow; the primary flow is approve-path below.)
    """
    state: AppState = request.app.state.app_state
    pipeline = _own_pipeline_or_403(state, pipeline_id, user)
    if pipeline.status not in ("planned", "error"):
        raise HTTPException(status_code=409, detail=f"pipeline is {pipeline.status!r}")
    asyncio.create_task(pipeline_orchestrator.run_pipeline(state, pipeline))
    return {"pipeline_id": pipeline_id, "status": "running"}


class ApprovePathIn(BaseModel):
    path_id: str


@router.post("/{pipeline_id}/approve-path")
async def approve_path(
    pipeline_id: str, payload: ApprovePathIn, request: Request,
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Approve one whole pathway and execute it end-to-end.

    The reviewer chose a viable path; this derives the per-scenario decisions
    that path prescribes and runs the pipeline auto-applying them (firing each
    step's action) with no further prompts.
    """
    state: AppState = request.app.state.app_state
    pipeline = _own_pipeline_or_403(state, pipeline_id, user)
    if pipeline.status not in ("planned", "error"):
        raise HTTPException(status_code=409, detail=f"pipeline is {pipeline.status!r}")
    try:
        prescribed = prescribed_for_path(pipeline.forecast, payload.path_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown/non-actionable path_id: {payload.path_id}")
    pipeline.chosen_path_id = payload.path_id
    asyncio.create_task(pipeline_orchestrator.run_pipeline_path(state, pipeline, prescribed))
    return {"pipeline_id": pipeline_id, "status": "running", "path_id": payload.path_id}
