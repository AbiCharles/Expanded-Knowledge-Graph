"""Aggregated case metrics for the dashboard.

Returns four charts' worth of data:
  - cases_by_status: counts per phase (current state of cases)
  - decisions_by_scenario: per-scenario breakdown of approve/reject/info/auto
  - cases_per_day: time series for the last 30 days
  - top_rejection_reasons: word-cloud-friendly list of rejection rationales

All queries scope to the current user (admins see across users).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select

from ..auth import CurrentUser, current_user
from ..persistence.db import CaseRow, LineageRow

router = APIRouter(tags=["metrics"], prefix="/metrics")


@router.get("/summary")
def metrics_summary(request: Request, user: CurrentUser = Depends(current_user)) -> dict:
    state = request.app.state.app_state
    db = state.database
    is_admin = user.role == "admin"

    with db.session() as session:
        base = select(CaseRow)
        if not is_admin:
            base = base.where(CaseRow.user_id == user.id)

        # 1. cases by phase
        phase_counts = dict(
            session.execute(
                select(CaseRow.phase, func.count(CaseRow.case_id))
                .where(*([CaseRow.user_id == user.id] if not is_admin else []))
                .group_by(CaseRow.phase)
            ).all()
        )

        # 2. decisions by scenario
        rows = session.execute(
            select(CaseRow.scenario_id, CaseRow.decision_kind, func.count(CaseRow.case_id))
            .where(*([CaseRow.user_id == user.id] if not is_admin else []))
            .where(CaseRow.scenario_id.is_not(None))
            .group_by(CaseRow.scenario_id, CaseRow.decision_kind)
        ).all()
        by_scenario: dict[str, dict[str, int]] = {}
        for sid, kind, count in rows:
            entry = by_scenario.setdefault(sid, {"approve": 0, "reject": 0, "request_more_info": 0, "auto_execute": 0, "in_progress": 0})
            if kind in entry:
                entry[kind] = int(count or 0)
            elif kind is None:
                entry["in_progress"] += int(count or 0)

        # 3. cases per day (last 30 days)
        cutoff = datetime.utcnow() - timedelta(days=30)
        day_rows = session.execute(
            select(
                func.date(CaseRow.created_at),
                func.count(CaseRow.case_id),
            )
            .where(*([CaseRow.user_id == user.id] if not is_admin else []))
            .where(CaseRow.created_at >= cutoff)
            .group_by(func.date(CaseRow.created_at))
            .order_by(func.date(CaseRow.created_at))
        ).all()
        cases_per_day = [{"date": str(d), "count": int(c or 0)} for d, c in day_rows]

        # 4. top rejection reasons (extract from lineage detail).
        # Lineage is keyed by the framework's case_id, not ours — JOIN
        # CaseRow.framework_case_id == LineageRow.case_id.
        rejection_rows = session.execute(
            select(LineageRow.detail, CaseRow.user_id)
            .join(CaseRow, CaseRow.framework_case_id == LineageRow.case_id)
            .where(LineageRow.action == "decided")
            .where(CaseRow.decision_kind == "reject")
            .where(*([CaseRow.user_id == user.id] if not is_admin else []))
        ).all()
        # Detail looks like "reject — <rationale>" (em-dash); split + collect.
        reasons: Counter[str] = Counter()
        for detail, _uid in rejection_rows:
            if not detail:
                continue
            for sep in (" — ", " - ", ": "):
                if sep in detail:
                    reason = detail.split(sep, 1)[1].strip()
                    # Trim follow-up annotations
                    reason = reason.split(" (")[0].strip()
                    if reason:
                        reasons[reason] += 1
                        break
        top_reasons = [{"reason": r, "count": c} for r, c in reasons.most_common(8)]

        # 5. headline tiles
        total_cases = session.execute(
            select(func.count(CaseRow.case_id))
            .where(*([CaseRow.user_id == user.id] if not is_admin else []))
        ).scalar() or 0
        complete_count = phase_counts.get("complete", 0)
        in_progress = sum(v for k, v in phase_counts.items() if k not in ("complete", "cancelled"))

    return {
        "scope": "all" if is_admin else f"user:{user.username}",
        "totals": {
            "all_cases": int(total_cases),
            "complete": int(complete_count or 0),
            "in_progress": int(in_progress),
        },
        "cases_by_status": [
            {"phase": k, "count": int(v or 0)} for k, v in sorted(phase_counts.items())
        ],
        "decisions_by_scenario": [
            {"scenario_id": sid, **counts} for sid, counts in sorted(by_scenario.items())
        ],
        "cases_per_day": cases_per_day,
        "top_rejection_reasons": top_reasons,
    }
