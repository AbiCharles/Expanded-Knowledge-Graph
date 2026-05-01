"""Scenario catalog endpoints — used by the frontend to populate suggested chips."""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["scenarios"])


@router.get("/scenarios")
def list_scenarios(request: Request) -> list[dict]:
    """Return the public-facing slice of each scenario for the chip row."""
    state = request.app.state.app_state
    rows: list[dict] = []
    for sc in state.scenarios.all():
        rows.append(
            {
                "id": sc["id"],
                "title": sc["title"],
                "domain": sc["domain"],
                "autonomous": bool(sc.get("autonomous")),
                "suggested_prompt": _suggested_prompt_for(sc),
            }
        )
    return rows


_BUILTIN_PROMPTS = {
    "SC-TC-007": "Override the SC-TC-001 block on order ORD-44216 — customer says they have an OFAC license.",
    "SC-PP-007": "Onboard Hemlock Precision Castings as a tier-1 EU supplier — annual spend ~$1.2M.",
    "SC-LN-002": "Switch shipment S-700412 from ocean to air to recover the schedule.",
    "SC-LN-STATUS-009": "What's the current ETA on shipment S-700499?",
    "SC-PP-AUTO-014": "Set the reorder point on SKU-EL-2210 to 200 units.",
    "SC-TC-008": "Run the live override flow with fresh data from registered sources.",
}


def _suggested_prompt_for(sc: dict) -> str:
    """Built-in scenarios use hand-written prompts; auto-generated chips derive
    theirs from the source id."""
    sid = sc["id"]
    if sid in _BUILTIN_PROMPTS:
        return _BUILTIN_PROMPTS[sid]
    if sid.startswith("SC-AUTO-"):
        source_id = sid[len("SC-AUTO-"):]
        # Match auto_scenario.suggested_prompt_for() but inline to avoid the
        # cross-import (and we don't have the spec here, only the scenario).
        label = source_id.replace("_", " ").replace("-", " ").strip()
        return f"Look up data from {label}"
    return ""
