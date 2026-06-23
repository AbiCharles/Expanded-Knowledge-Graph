"""W8 — agent-orchestrator findings drop-box.

The agent_orchestrator companion app POSTs its run findings here
(program-manager routing + alternate-outreach status) after each run
completes. The fabric frontend reads them via GET on the deep-link
auto-launch path so the knowledge graph can label its Program
terminals with PM names and its alternate-supplier terminals with
the outreach status.

In-memory + intentionally no-auth: the data is demo-only, ephemeral,
and the orchestrator runs in the same Fly org. Holds the LATEST
payload; a new POST overwrites. Cleared on process restart.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------
# Wire-format models. Both halves of the payload are optional so the
# orchestrator can grow the schema without breaking older fabric builds.
# ---------------------------------------------------------------------
class AlternateOutreachEntry(BaseModel):
    supplier_id: str
    name: str
    via: Optional[str] = None
    # Used only on the blocked side; harmless if present elsewhere.
    reason: Optional[str] = None


class AlternateOutreach(BaseModel):
    primary: list[AlternateOutreachEntry] = Field(default_factory=list)
    blocked: list[AlternateOutreachEntry] = Field(default_factory=list)


class Findings(BaseModel):
    # Map of program_id (e.g. PRG-AERO-MIRAGE) → "rachel.tan @ Aeronova (Mirage)".
    program_managers: dict[str, str] = Field(default_factory=dict)
    alternate_outreach: AlternateOutreach = Field(default_factory=AlternateOutreach)
    # Optional metadata so the fabric can show "X seconds ago" + which
    # run produced these findings.
    posted_at: Optional[str] = None
    run_id: Optional[str] = None


# Module-level singleton holding the latest payload. Reset on import.
_latest: Optional[Findings] = None


@router.post("/aeronova/findings")
def post_findings(payload: Findings) -> dict[str, Any]:
    global _latest
    _latest = payload
    log.info(
        "Aeronova findings posted · %d PMs · primary=%d blocked=%d · run_id=%s",
        len(payload.program_managers),
        len(payload.alternate_outreach.primary),
        len(payload.alternate_outreach.blocked),
        payload.run_id,
    )
    return {"ok": True}


@router.get("/aeronova/findings", response_model=Optional[Findings])
def get_findings() -> Optional[Findings]:
    """Returns the latest payload or null if nothing has been posted yet.

    Used by the fabric frontend on the deep-link auto-launch path
    (?launch=aeronova&view=pathways) to overlay agent findings on the
    knowledge graph.
    """
    return _latest
