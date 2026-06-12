"""Phase 3 — pattern-mining + promote/demote over `case_highlighted_facts`.

This module ships both sides of the compounding-context loop:

  Phase 3a — `GET /insights/patterns` aggregates the per-case
  load-bearing-fact captures from Phase 2 and returns recurring
  drivers grouped by (scenario, decision_kind, fact_ontology_type).

  Phase 3b — `POST /insights/patterns/promote` writes a recurring
  pattern into the scenario's `auto_promoted_patterns` list and bumps
  the scenario to a new version via Phase 1 register(). When a future
  case binds facts matching a promoted pattern, the case-detail
  endpoint surfaces it as an advisory chip ("in 8 of 8 similar cases,
  reviewers rejected for SanctionsProximity").

  `POST /insights/patterns/demote` reverses a promotion.

Admin-only throughout: pattern data shapes who-overrides-what
disclosures across all reviewers; promoting a pattern modifies the
shared scenario every operator runs against.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..auth import CurrentUser, current_user
from ..persistence.db import CaseHighlightedFactRow, CaseRow


router = APIRouter(tags=["insights"], prefix="/insights")


# Default guardrails — the admin can override per-request. Defaults
# are deliberately permissive so a small demo dataset can illustrate
# the loop; real deployments should crank them up.
DEFAULT_MIN_CASE_COUNT = 2
DEFAULT_MIN_SHARE_OF_KIND_PCT = 50.0


# Shape stored under `scenario["auto_promoted_patterns"]` (one entry
# per promotion). Documented here, not enforced by a Pydantic model
# — the scenario YAML is loose-shape on purpose so future trigger
# kinds can be added without a migration.
#
#   {
#     "id": "auto-<uuid>",
#     "decision_kind": "reject",
#     "trigger": {"ontology_type": "SanctionsProximity", "min_facts": 1},
#     "suggested_rationale": "<reason text>",
#     "metadata": {
#       "promoted_at": "<iso8601>",
#       "promoted_by": "<username>",
#       "source_case_count": int,
#       "source_share_of_kind_pct": float,
#       "source_total_decided": int,
#     },
#   }


# The denorm table fills proportionally to the cap in decisions.py.
# 1 row per highlighted fact per case → for "% of decisions with this
# driver" we have to count *distinct* cases, not rows.
def _require_admin(user: CurrentUser) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin only")


@router.get("/patterns")
def patterns(request: Request, user: CurrentUser = Depends(current_user)) -> dict:
    """Recurring override patterns across all scenarios.

    Shape:
        {
          "generated_at_seconds": float,
          "scenarios": [
            {
              "scenario_id": str,
              "total_decided_cases": int,
              "patterns": [
                {
                  "decision_kind": str,
                  "fact_ontology_type": str,
                  "case_count": int,                  # distinct cases
                  "share_of_decisions": float,        # case_count / total decisions on scenario
                  "share_of_decision_kind": float,    # case_count / decisions of same kind on scenario
                  "sample_fact_ids": [str, ...],      # up to 3 examples
                }, ...
              ]
            }, ...
          ]
        }

    Sorted patterns-within-scenario by `case_count` desc.
    """
    _require_admin(user)
    state = request.app.state.app_state
    db = state.database

    with db.session() as session:
        # 1. Per-scenario totals — "how many decided cases of this
        #    scenario exist?" — needed for the denominator on
        #    share_of_decisions.
        decision_totals_row = session.execute(
            select(
                CaseRow.scenario_id,
                CaseRow.decision_kind,
                func.count(CaseRow.case_id).label("n"),
            )
            .where(CaseRow.decision_kind.is_not(None))
            .where(CaseRow.scenario_id.is_not(None))
            .group_by(CaseRow.scenario_id, CaseRow.decision_kind)
        ).all()

        per_scenario_decision_counts: dict[str, dict[str, int]] = {}
        per_scenario_totals: dict[str, int] = {}
        for sid, kind, n in decision_totals_row:
            per_scenario_decision_counts.setdefault(sid, {})[kind] = int(n)
            per_scenario_totals[sid] = per_scenario_totals.get(sid, 0) + int(n)

        # 2. Pattern aggregate — count DISTINCT cases per
        #    (scenario_id, decision_kind, fact_ontology_type).
        pattern_rows = session.execute(
            select(
                CaseHighlightedFactRow.scenario_id,
                CaseHighlightedFactRow.decision_kind,
                CaseHighlightedFactRow.fact_ontology_type,
                func.count(func.distinct(CaseHighlightedFactRow.case_id)).label("n"),
            )
            .group_by(
                CaseHighlightedFactRow.scenario_id,
                CaseHighlightedFactRow.decision_kind,
                CaseHighlightedFactRow.fact_ontology_type,
            )
            .order_by(func.count(func.distinct(CaseHighlightedFactRow.case_id)).desc())
        ).all()

        # 3. Up-to-3 sample fact_ids per (scenario, decision_kind,
        #    ontology_type) so the UI can show "e.g. SUP-001-PROX,
        #    SUP-007-PROX" without dumping the whole tail.
        sample_rows = session.execute(
            select(
                CaseHighlightedFactRow.scenario_id,
                CaseHighlightedFactRow.decision_kind,
                CaseHighlightedFactRow.fact_ontology_type,
                CaseHighlightedFactRow.fact_id,
            ).distinct()
        ).all()

    samples: dict[tuple[str, str, str], list[str]] = {}
    for sid, kind, ot, fact_id in sample_rows:
        bucket = samples.setdefault((sid, kind, ot), [])
        if fact_id and len(bucket) < 3 and fact_id not in bucket:
            bucket.append(fact_id)

    # 4. Stitch into the response shape.
    by_scenario: dict[str, dict] = {}
    for sid, kind, ot, n in pattern_rows:
        if sid is None or kind is None or ot is None:
            continue
        n = int(n)
        denom_total = per_scenario_totals.get(sid, 0) or 1
        denom_kind = per_scenario_decision_counts.get(sid, {}).get(kind, 0) or 1
        entry = by_scenario.setdefault(sid, {
            "scenario_id": sid,
            "total_decided_cases": per_scenario_totals.get(sid, 0),
            "patterns": [],
        })
        entry["patterns"].append({
            "decision_kind": kind,
            "fact_ontology_type": ot,
            "case_count": n,
            "share_of_decisions": round(100.0 * n / denom_total, 1),
            "share_of_decision_kind": round(100.0 * n / denom_kind, 1),
            "sample_fact_ids": samples.get((sid, kind, ot), []),
        })

    # Sort scenarios by their total-decided-cases desc so the most
    # active workflow ranks first.
    scenarios = sorted(
        by_scenario.values(),
        key=lambda s: s["total_decided_cases"],
        reverse=True,
    )

    import time
    return {"generated_at_seconds": time.time(), "scenarios": scenarios}


# =============================================================================
# Phase 3b — promote / demote
# =============================================================================
class PromoteIn(BaseModel):
    """Body for POST /insights/patterns/promote."""
    scenario_id: str = Field(min_length=1)
    decision_kind: str = Field(pattern="^(approve|reject|request_more_info)$")
    fact_ontology_type: str = Field(min_length=1)
    # Optional override for the rationale text the orchestrator will
    # pre-fill when the trigger fires on a future case. Defaults to a
    # generic "promoted from N cases at S%" line.
    suggested_rationale: Optional[str] = None
    # Per-request guardrail overrides — strictly checked against the
    # CURRENT aggregate, not whatever the UI last rendered, so a stale
    # InsightsModal can't promote a pattern whose confidence has since
    # decayed.
    min_case_count: int = DEFAULT_MIN_CASE_COUNT
    min_share_of_kind_pct: float = DEFAULT_MIN_SHARE_OF_KIND_PCT


class DemoteIn(BaseModel):
    scenario_id: str = Field(min_length=1)
    pattern_id: str = Field(min_length=1)


def _stats_for_pattern(
    db, scenario_id: str, decision_kind: str, ontology_type: str,
) -> dict[str, Any]:
    """Recompute (case_count, share_of_decision_kind, total_decided)
    against the live captures. Defends against a UI that promoted off
    a stale aggregate."""
    with db.session() as session:
        case_count = int(session.execute(
            select(func.count(func.distinct(CaseHighlightedFactRow.case_id)))
            .where(CaseHighlightedFactRow.scenario_id == scenario_id)
            .where(CaseHighlightedFactRow.decision_kind == decision_kind)
            .where(CaseHighlightedFactRow.fact_ontology_type == ontology_type)
        ).scalar() or 0)
        decisions_of_kind = int(session.execute(
            select(func.count(CaseRow.case_id))
            .where(CaseRow.scenario_id == scenario_id)
            .where(CaseRow.decision_kind == decision_kind)
        ).scalar() or 0)
        decisions_total = int(session.execute(
            select(func.count(CaseRow.case_id))
            .where(CaseRow.scenario_id == scenario_id)
            .where(CaseRow.decision_kind.is_not(None))
        ).scalar() or 0)
    share = (100.0 * case_count / decisions_of_kind) if decisions_of_kind else 0.0
    return {
        "case_count": case_count,
        "decisions_of_kind": decisions_of_kind,
        "decisions_total": decisions_total,
        "share_of_kind_pct": round(share, 1),
    }


@router.post("/patterns/promote")
def promote(payload: PromoteIn, request: Request,
            user: CurrentUser = Depends(current_user)) -> dict:
    """Promote a Phase 2 pattern into the scenario YAML, bumping the
    scenario version via Phase 1 register().

    Guardrails (configurable per-request):
      - case_count >= min_case_count
      - share_of_decision_kind_pct >= min_share_of_kind_pct

    Idempotent: re-promoting an equivalent trigger replaces the
    existing entry (preserves the original id) so the audit trail
    stays single-row per scenario+trigger combination.
    """
    _require_admin(user)
    state = request.app.state.app_state

    sc = state.scenarios.get(payload.scenario_id)
    if sc is None:
        raise HTTPException(status_code=404, detail="unknown scenario")

    stats = _stats_for_pattern(
        state.database, payload.scenario_id,
        payload.decision_kind, payload.fact_ontology_type,
    )
    if stats["case_count"] < payload.min_case_count:
        raise HTTPException(
            status_code=409,
            detail=(
                f"guardrail: case_count={stats['case_count']} < "
                f"min_case_count={payload.min_case_count}"
            ),
        )
    if stats["share_of_kind_pct"] < payload.min_share_of_kind_pct:
        raise HTTPException(
            status_code=409,
            detail=(
                f"guardrail: share_of_decision_kind="
                f"{stats['share_of_kind_pct']}% < "
                f"min_share_of_kind_pct={payload.min_share_of_kind_pct}%"
            ),
        )

    existing_list = list(sc.get("auto_promoted_patterns") or [])
    matches_existing = [
        i for i, p in enumerate(existing_list)
        if (p.get("decision_kind") == payload.decision_kind
            and (p.get("trigger") or {}).get("ontology_type") == payload.fact_ontology_type)
    ]
    pattern_id = (
        existing_list[matches_existing[0]]["id"]
        if matches_existing
        else f"auto-{uuid.uuid4().hex[:12]}"
    )
    suggested = payload.suggested_rationale or (
        f"Reviewers cited {payload.fact_ontology_type} in {stats['case_count']} "
        f"of {stats['decisions_of_kind']} {payload.decision_kind} decisions "
        f"on this scenario (auto-promoted pattern)."
    )
    new_entry = {
        "id": pattern_id,
        "decision_kind": payload.decision_kind,
        "trigger": {
            "ontology_type": payload.fact_ontology_type,
            "min_facts": 1,
        },
        "suggested_rationale": suggested,
        "metadata": {
            "promoted_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "promoted_by": user.username,
            "source_case_count": stats["case_count"],
            "source_share_of_kind_pct": stats["share_of_kind_pct"],
            "source_total_decided": stats["decisions_total"],
        },
    }
    if matches_existing:
        existing_list[matches_existing[0]] = new_entry
    else:
        existing_list.append(new_entry)
    sc["auto_promoted_patterns"] = existing_list
    state.scenarios.register(sc, persist=True)

    return {
        "scenario_id": payload.scenario_id,
        "version": sc.get("version"),
        "pattern_id": pattern_id,
        "replaced": bool(matches_existing),
        "stats": stats,
    }


@router.post("/patterns/demote")
def demote(payload: DemoteIn, request: Request,
           user: CurrentUser = Depends(current_user)) -> dict:
    """Remove a previously-promoted pattern from a scenario, bumping
    the version. Inverse of /promote — keeps the audit trail honest."""
    _require_admin(user)
    state = request.app.state.app_state

    sc = state.scenarios.get(payload.scenario_id)
    if sc is None:
        raise HTTPException(status_code=404, detail="unknown scenario")

    existing_list = list(sc.get("auto_promoted_patterns") or [])
    remaining = [p for p in existing_list if p.get("id") != payload.pattern_id]
    if len(remaining) == len(existing_list):
        raise HTTPException(status_code=404, detail="pattern_id not found")

    sc["auto_promoted_patterns"] = remaining
    state.scenarios.register(sc, persist=True)

    return {
        "scenario_id": payload.scenario_id,
        "version": sc.get("version"),
        "pattern_id": payload.pattern_id,
        "remaining_patterns": len(remaining),
    }
