"""Phase 3a — pattern-mining endpoint over `case_highlighted_facts`.

The compounding-context roadmap's third pillar is "promote recurring
override patterns into new scenario versions." This module ships the
read side of that loop: aggregate the per-case load-bearing-fact
captures from Phase 2 and surface recurring drivers grouped by
(scenario, decision_kind, fact_ontology_type).

Phase 3b (not in this module) will use the same aggregates as input to
an admin-only "draft a new scenario version" flow.

Admin-only: pattern data shapes who-overrides-what disclosures across
all reviewers, so we don't expose it to operators.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from ..auth import CurrentUser, current_user
from ..persistence.db import CaseHighlightedFactRow, CaseRow


router = APIRouter(tags=["insights"], prefix="/insights")


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
