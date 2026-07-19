"""RCA analysis endpoint.

Returns the STRUCTURED synthesis outputs (5-Why, Ishikawa, Pareto,
evidence-graph) for a case so the frontend can render each method's native
chart (bar chart, fishbone, chain, C-scan) plus the supporting evidence
"documents". The case pipeline flattens synthesis into fact cards; this
re-derives the structured shapes on demand.

Stateless: it re-binds the case's proposal evidence via the ontology
resolver (the same path the binder uses) and re-runs the synthesis modes.
Deterministic under `LLM_PROVIDER=fake`.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import CurrentUser, current_user
from ..binders import _facts_from_stage
from ..rca_synthesis import (
    _problem_statement,
    run_evidence_graph_synthesis,
    run_five_why_synthesis,
    run_ishikawa_synthesis,
    run_pareto_synthesis,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/rca", tags=["rca"])


class RcaAnalysisRequest(BaseModel):
    case_id: str = Field("", description="Case whose scenario carries the part_id + evidence")
    part_id: str = Field("", description="Override the part_id from the case scenario")


def _rca_vision_base(state) -> str:
    """The rca_vision http source's base_url (points at the RCA service)."""
    for spec in state.data_sources.specs():
        if spec.id == "rca_vision":
            return (spec.config.get("base_url") or "").rstrip("/")
    return "http://localhost:8000"


def _fetch_cscan_svg(state, part_id: str) -> str | None:
    """Fetch the C-scan SVG server-side and return it inline, so the browser
    renders it as a data URI (works cross-origin and on Fly without exposing
    the internal RCA service or needing an authed image request)."""
    base = _rca_vision_base(state)
    if not base:
        return None
    try:
        r = httpx.get(f"{base}/api/cscan/{part_id}.svg", timeout=6.0)
        r.raise_for_status()
        return r.text
    except httpx.HTTPError:
        return None


@router.post("/analysis")
async def rca_analysis(
    payload: RcaAnalysisRequest,
    request: Request,
    _user: CurrentUser = Depends(current_user),
) -> dict:
    state = request.app.state.app_state

    scenario = None
    if payload.case_id:
        case = state.cases.get(payload.case_id)
        if case is not None and case.scenario_id:
            scenario = state.scenarios.get(case.scenario_id)
    if scenario is None:
        raise HTTPException(404, "no RCA scenario resolvable for this case")

    action_payload = dict(scenario.get("action_payload") or {})
    if payload.part_id:
        action_payload["part_id"] = payload.part_id

    proposal_def = (scenario.get("stages") or {}).get("proposal") or {}
    # Re-bind the proposal evidence (Anomaly / EvidenceNode / Defect / PriorNCR).
    facts, _ = _facts_from_stage(
        proposal_def, ontology=state.ontology_resolver, payload=action_payload
    )
    # Also bind the review stage so the CAPA recommendations show as documents.
    review_def = (scenario.get("stages") or {}).get("review") or {}
    review_facts, _ = _facts_from_stage(
        review_def, ontology=state.ontology_resolver, payload=action_payload
    )

    five = await run_five_why_synthesis(state.llm, evidence_facts=facts, payload=action_payload)
    ish = await run_ishikawa_synthesis(state.llm, evidence_facts=facts, payload=action_payload)
    par = await run_pareto_synthesis(state.llm, evidence_facts=facts, payload=action_payload)
    eg = await run_evidence_graph_synthesis(state.llm, evidence_facts=facts, payload=action_payload)

    # Vision — pull the C-scan image + typed fields off the bound Defect fact
    # (from the rca_vision http source). None when the vision service is down.
    vision = None
    for f in facts:
        if f.ref.ontology_type == "Defect" or f.ref.source.startswith("http:rca_vision"):
            p = f.payload
            vision = {
                "image_url": p.get("image_url"),
                "image_svg": _fetch_cscan_svg(state, action_payload.get("part_id", "")),
                "defect_type": p.get("defect_type"),
                "severity": p.get("severity"),
                "location": p.get("location"),
                "candidate_causes": p.get("candidate_causes"),
                "observations": p.get("observations"),
                "title": p.get("title"),
                "summary": p.get("summary"),
            }
            break

    # Bound evidence + review CAPAs become the "documents" for each tab.
    evidence = [
        {
            "source": f.ref.source,
            "ontology_type": f.ref.ontology_type,
            "id": f.ref.id,
            "title": f.payload.get("title"),
            "summary": f.payload.get("summary"),
            "via_ontology": f.payload.get("via_ontology"),
        }
        for f in (facts + review_facts)
    ]

    return {
        "problem": _problem_statement(action_payload),
        "part_id": action_payload.get("part_id", ""),
        "defect_type": action_payload.get("defect_type", ""),
        "vision": vision,
        "evidence": evidence,
        "five_why": five.model_dump(),
        "ishikawa": ish.model_dump(),
        "pareto": par.model_dump(),
        "evidence_graph": eg.model_dump(),
    }
