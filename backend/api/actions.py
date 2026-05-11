"""Action-registry endpoints — manage write actions + preview NL picks.

Mirrors `backend/api/ontologies.py`. Mutations require admin (default
seeded actions refuse delete).
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from ..actions import (
    ActionError,
    NLActionParseError,
    parse_action,
    parse_nl_action,
)

router = APIRouter(tags=["actions"])


# =============================================================================
# Schemas
# =============================================================================
class ActionSummary(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    hitl: bool
    executor_kind: str
    target_source: Optional[str] = None
    argument_count: int
    default: bool


class RawActionIn(BaseModel):
    """Programmatic upload — content (YAML or JSON) or pre-parsed dict."""

    content: Optional[str] = None
    document: Optional[dict[str, Any]] = None


class PreviewNLActionIn(BaseModel):
    prompt: str


# =============================================================================
# List / fetch
# =============================================================================
@router.get("/actions", response_model=list[ActionSummary])
def list_actions(request: Request) -> list[ActionSummary]:
    state = request.app.state.app_state
    out: list[ActionSummary] = []
    for a in state.actions.all():
        target = getattr(a.executor, "data_source", None)
        out.append(
            ActionSummary(
                id=a.id,
                title=a.title,
                description=a.description,
                hitl=a.hitl,
                executor_kind=a.executor.kind,
                target_source=target,
                argument_count=len(a.arguments),
                default=a.default,
            )
        )
    return out


@router.get("/actions/{action_id}")
def get_action(action_id: str, request: Request):
    state = request.app.state.app_state
    a = state.actions.get(action_id)
    if a is None:
        raise HTTPException(404, f"unknown action {action_id!r}")
    return a.model_dump(mode="json")


# =============================================================================
# Upload (multipart) and raw upload
# =============================================================================
@router.post("/actions")
async def upload_action(request: Request, file: UploadFile = File(...)):
    raw = await file.read()
    try:
        action = parse_action(raw)
    except ActionError as exc:
        raise HTTPException(400, str(exc))
    state = request.app.state.app_state
    state.actions.register(action)
    return {"id": action.id, "title": action.title}


@router.post("/actions/raw")
def upload_action_raw(body: RawActionIn, request: Request):
    if (body.content is None) == (body.document is None):
        raise HTTPException(400, "provide exactly one of `content` or `document`")
    payload = body.content if body.content is not None else body.document
    try:
        action = parse_action(payload)
    except ActionError as exc:
        raise HTTPException(400, str(exc))
    state = request.app.state.app_state
    state.actions.register(action)
    return {"id": action.id, "title": action.title}


@router.delete("/actions/{action_id}")
def delete_action(action_id: str, request: Request):
    state = request.app.state.app_state
    if state.actions.get(action_id) is None:
        raise HTTPException(404, f"unknown action {action_id!r}")
    try:
        state.actions.unregister(action_id)
    except ActionError as exc:
        # Default actions refuse deletion.
        raise HTTPException(400, str(exc))
    return {"id": action_id, "removed": True}


# =============================================================================
# Preview (no execution) — operator can sanity-check what the LLM picked
# =============================================================================
@router.post("/actions/preview-nl")
async def preview_nl(body: PreviewNLActionIn, request: Request):
    state = request.app.state.app_state
    try:
        match = await parse_nl_action(body.prompt, state.actions, state.llm)
    except NLActionParseError as exc:
        raise HTTPException(400, str(exc))
    action = state.actions.require(match.action_id)
    return {
        "action_id": match.action_id,
        "title": action.title,
        "executor_kind": action.executor.kind,
        "target_source": getattr(action.executor, "data_source", None),
        "arguments": match.arguments,
        "confidence": match.confidence,
        "rationale": match.rationale,
        "hitl": action.hitl,
    }
