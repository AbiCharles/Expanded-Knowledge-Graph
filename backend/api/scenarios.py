"""Scenario catalog endpoints — used by the frontend to populate suggested chips."""
from __future__ import annotations

import re
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(tags=["scenarios"])


@router.get("/scenarios")
def list_scenarios(request: Request) -> list[dict]:
    """Return the public-facing slice of each scenario for the chip row.

    Includes per-scenario run history (count + last run) queried from the
    persisted cases table — so the frontend can show usage stats on each chip.
    """
    state = request.app.state.app_state
    history = _scenario_run_history(state)
    rows: list[dict] = []
    for sc in state.scenarios.all():
        sid = sc["id"]
        h = history.get(sid, {})
        rows.append(
            {
                "id": sid,
                "title": sc["title"],
                "domain": sc["domain"],
                "autonomous": bool(sc.get("autonomous")),
                "suggested_prompt": _suggested_prompt_for(sc),
                "run_count": int(h.get("count", 0)),
                "last_run_at": h.get("last_run_at"),
                "approve_count": int(h.get("approve_count", 0)),
                "reject_count": int(h.get("reject_count", 0)),
                "auto_count": int(h.get("auto_count", 0)),
            }
        )
    return rows


def _scenario_run_history(state) -> dict[str, dict[str, Any]]:
    """Aggregate counts + last-run timestamp per scenario_id from the cases table."""
    from sqlalchemy import func, select
    from ..persistence.db import CaseRow

    out: dict[str, dict[str, Any]] = {}
    db = state.database
    with db.session() as session:
        # Total run count + last run
        rows = session.execute(
            select(
                CaseRow.scenario_id,
                func.count(CaseRow.case_id),
                func.max(CaseRow.updated_at),
            ).group_by(CaseRow.scenario_id)
        ).all()
        for sid, count, last in rows:
            if sid:
                out[sid] = {
                    "count": int(count or 0),
                    "last_run_at": last.isoformat() if last else None,
                    "approve_count": 0,
                    "reject_count": 0,
                    "auto_count": 0,
                }
        # Per-decision counts
        decisions = session.execute(
            select(
                CaseRow.scenario_id,
                CaseRow.decision_kind,
                func.count(CaseRow.case_id),
            )
            .where(CaseRow.scenario_id.is_not(None))
            .where(CaseRow.decision_kind.is_not(None))
            .group_by(CaseRow.scenario_id, CaseRow.decision_kind)
        ).all()
        for sid, kind, count in decisions:
            entry = out.setdefault(sid, {"count": 0, "last_run_at": None,
                                          "approve_count": 0, "reject_count": 0, "auto_count": 0})
            if kind == "approve":
                entry["approve_count"] = int(count or 0)
            elif kind == "reject":
                entry["reject_count"] = int(count or 0)
            elif kind == "auto_execute":
                entry["auto_count"] = int(count or 0)
    return out


_BUILTIN_PROMPTS = {
    "SC-TC-007": "Override the SC-TC-001 block on order ORD-44216 — customer says they have an OFAC license.",
    "SC-PP-007": "Onboard Hemlock Precision Castings as a tier-1 EU supplier — annual spend ~$1.2M.",
    "SC-LN-002": "Switch shipment S-700412 from ocean to air to recover the schedule.",
    "SC-LN-STATUS-009": "What's the current ETA on shipment S-700499?",
    "SC-PP-AUTO-014": "Set the reorder point on SKU-EL-2210 to 200 units.",
    "SC-TC-008": "Run the live override flow with fresh data from registered sources.",
}


_VALID_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{1,63}$")


class SaveScenarioIn(BaseModel):
    """Save-from-playground request body.

    Builds an autonomous lookup scenario around an arbitrary SQL query the
    operator has been iterating in the Query playground. Almost every field has
    a sensible default — the only required field is `data_source` (which the
    UI knows from context).
    """
    scenario_id: Optional[str] = None  # auto-generated from title if omitted
    title: str
    description: str = ""
    data_source: str
    ontology_type: str = "Record"
    sql: str
    params: dict[str, Any] = Field(default_factory=dict)
    match_keywords: list[str] = Field(default_factory=list)
    clarifying_question: Optional[str] = None
    closing_message: Optional[str] = None
    suggested_prompt: Optional[str] = None


@router.post("/scenarios")
def save_scenario(payload: SaveScenarioIn, request: Request) -> dict:
    """Persist a customised scenario built around a registered data source's
    arbitrary SQL. The chip appears in the operator console immediately."""
    state = request.app.state.app_state
    if state.data_sources.get(payload.data_source) is None:
        raise HTTPException(status_code=404, detail=f"unknown data_source {payload.data_source!r}")
    if not (payload.sql or "").strip():
        raise HTTPException(status_code=400, detail="sql is required")
    if not (payload.title or "").strip():
        raise HTTPException(status_code=400, detail="title is required")

    sid = payload.scenario_id or _slugify(payload.title)
    if not sid.startswith("SC-"):
        sid = f"SC-CUSTOM-{sid}"
    if not _VALID_ID_RE.match(sid):
        raise HTTPException(status_code=400, detail=f"invalid scenario id {sid!r}")
    if state.scenarios.get(sid):
        raise HTTPException(status_code=409, detail=f"scenario {sid!r} already exists")

    # Conflict detection: warn-only — return 409 with a structured payload if
    # any existing scenario shares > 50% of the proposed keywords. Lets the
    # frontend offer "use these anyway" rather than silently degrading the
    # classifier. Disable with `?force=1`.
    overlap = _detect_keyword_conflict(state.scenarios, payload.match_keywords or [])
    if overlap and not request.query_params.get("force"):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "keyword_conflict",
                "message": (
                    "Some of these keywords overlap heavily with an existing scenario. "
                    "The classifier may pick the wrong one. Re-submit with ?force=1 to save anyway."
                ),
                "conflicts": overlap,
            },
        )

    scenario = _build_custom_scenario(payload, sid)
    state.scenarios.register(scenario)
    # Track the suggested prompt on the scenario itself so /api/scenarios picks
    # it up below (we don't have a separate registry for prompts).
    if payload.suggested_prompt:
        scenario["_custom_suggested_prompt"] = payload.suggested_prompt
    return {"scenario_id": sid}


@router.delete("/scenarios/{scenario_id}")
def delete_scenario(scenario_id: str, request: Request) -> dict:
    """Remove an operator-saved scenario. Built-in (`SC-TC-*`, `SC-PP-*`,
    `SC-LN-*`) scenarios cannot be deleted via this endpoint."""
    state = request.app.state.app_state
    sc = state.scenarios.get(scenario_id)
    if sc is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    if not (scenario_id.startswith("SC-CUSTOM-") or scenario_id.startswith("SC-AUTO-")):
        raise HTTPException(
            status_code=400,
            detail="only operator-saved (SC-CUSTOM-*) or auto (SC-AUTO-*) scenarios can be removed",
        )
    state.scenarios.unregister(scenario_id)
    return {"scenario_id": scenario_id, "removed": True}


def _slugify(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text.strip())[:48].strip("_") or "untitled"


def _detect_keyword_conflict(
    scenarios, proposed: list[str], threshold: float = 0.5
) -> list[dict[str, Any]]:
    """Return any existing scenarios that share ≥ threshold of `proposed`."""
    if not proposed:
        return []
    proposed_set = {k.strip().lower() for k in proposed if k.strip()}
    if not proposed_set:
        return []
    conflicts: list[dict[str, Any]] = []
    for sc in scenarios.all():
        existing = {k.strip().lower() for k in sc.get("match_keywords", []) if k.strip()}
        if not existing:
            continue
        overlap = proposed_set & existing
        if len(overlap) / len(proposed_set) >= threshold:
            conflicts.append({
                "scenario_id": sc["id"],
                "title": sc["title"],
                "shared_keywords": sorted(overlap),
                "overlap_pct": round(len(overlap) / len(proposed_set), 2),
            })
    return conflicts


def _build_custom_scenario(p: SaveScenarioIn, sid: str) -> dict[str, Any]:
    """Inline-fact agent intake stage (policy + scope) plus a single proposal
    stage that runs the operator's SQL via the data source. Autonomous."""
    keywords = list({k.strip().lower() for k in p.match_keywords if k.strip()})
    if not keywords:
        keywords = [p.title.lower(), sid.lower()]
    interpreted = f"run a custom lookup against {p.data_source}"

    return {
        "id": sid,
        "title": p.title,
        "domain": "Custom data sources",
        "autonomous": True,
        "actor_id": "agent-data-lookup",
        "operator_role": {"label": "Operator", "name": "data.analyst"},
        "action_type": "data_lookup",
        "action_payload": {
            "source_id": p.data_source,
            "ontology_type": p.ontology_type,
            "scope": "data.read",
        },
        "match_keywords": keywords,
        "interpreted_as": interpreted,
        "clarifying_question": (
            p.clarifying_question
            or f"Run the saved <strong>{p.title}</strong> lookup against "
               f"<code>{p.data_source}</code>? Read-only · no human review required."
        ),
        "auto_approval_guardrail": "GR-AUTO-LOOKUP",
        "auto_approval_reason": (
            f"Operator-saved query against {p.data_source!r}. Read-only within data.read scope."
        ),
        "closing_message": (
            p.closing_message
            or f"Done — pulled rows from <code>{p.data_source}</code> using the saved "
               f"<strong>{p.title}</strong> query."
        ),
        "stages": {
            "agent_intake": {
                "binder": "CustomLookupAgentBinder/1.0",
                "facts": [
                    {
                        "source": "kf:graph",
                        "ontology_type": "Policy",
                        "id": "POL-AUTO-LOOKUP",
                        "uri": "kf.tcs/policy/POL-AUTO-LOOKUP",
                        "title": "Autonomous data lookup policy",
                        "payload": "Operator-saved queries against registered data sources are autonomous within data.read.",
                    },
                    {
                        "source": "iam:scopes",
                        "ontology_type": "ActorScope",
                        "id": "agent-data-lookup",
                        "uri": "iam.tcs/actors/agent-data-lookup",
                        "title": "Actor scope",
                        "payload": f"Scopes: data.read · operator-saved scenario: {sid}",
                    },
                ],
            },
            "proposal": {
                "binder": "CustomLookupProposalBinder/1.0",
                "queries": [
                    {
                        "data_source": p.data_source,
                        "ontology_type": p.ontology_type,
                        "filter": {**p.params},
                        "purpose": p.description or f"Saved query: {p.title}",
                        # The custom SQL is carried alongside so a future binder
                        # variant can use it directly. The current binder only
                        # uses the registered source's saved query, so this
                        # field is informational for now.
                        "sql_override": p.sql,
                    }
                ],
            },
        },
        "outcomes": {
            "auto_execute": {
                "headline": f"Auto-executed — {p.title}",
                "detail": f"Lookup against {p.data_source} completed.",
            },
        },
        "_custom_for_source": p.data_source,
        "_custom_suggested_prompt": p.suggested_prompt,
    }


def _suggested_prompt_for(sc: dict) -> str:
    """Built-in scenarios use hand-written prompts; auto-generated chips derive
    theirs from the source id; operator-saved scenarios use a stored prompt."""
    sid = sc["id"]
    custom = sc.get("_custom_suggested_prompt")
    if custom:
        return str(custom)
    if sid in _BUILTIN_PROMPTS:
        return _BUILTIN_PROMPTS[sid]
    if sid.startswith("SC-AUTO-"):
        source_id = sid[len("SC-AUTO-"):]
        label = source_id.replace("_", " ").replace("-", " ").strip()
        return f"Look up data from {label}"
    if sid.startswith("SC-CUSTOM-"):
        return f"Run {sc.get('title', sid)}"
    return ""
