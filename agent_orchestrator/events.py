"""SSE event schema for the agent run.

Every event the orchestrator emits flows through `AgentEvent`. The
frontend's `/agent-run` view reads `type` to pick a card variant and
`payload` for the body. `fabric_link` (when present) is what powers
the Naresh handoff — each fabric-query event carries the URL that
opens the corresponding fabric component.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


EventType = Literal[
    "news_source_detected",
    "risk_detected",
    "investigation_started",
    "agent_thinking",
    "fabric_query",
    "fabric_response",
    "tier1_buyers_found",
    "programs_at_risk_identified",
    "alternates_surfaced",
    "subagents_spawned",
    "subagent_started",
    "subagent_progress",
    "subagent_completed",
    "run_completed",
    "error",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AgentEvent(BaseModel):
    """Wire-format event flowing over SSE to the frontend."""

    type: EventType
    agent_id: str
    at: str = Field(default_factory=_now_iso)
    payload: dict[str, Any] = Field(default_factory=dict)
    # Optional deep-link into the Knowledge Fabric so Naresh can pivot
    # to the underlying component after the agent run completes. Only
    # populated on events that came from a fabric call.
    fabric_link: Optional[str] = None


class StartRunRequest(BaseModel):
    """Body for POST /api/agent-run/start.

    Today only the Aeronova / SUP-021 narrative is wired, so the request
    is parameterless; the orchestrator hard-codes the failing supplier
    id. Kept as a model so the schema can grow without breaking the
    frontend API surface.
    """

    pass


class StartRunResponse(BaseModel):
    run_id: str
