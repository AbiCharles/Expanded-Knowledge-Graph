"""Historical case-decision frequencies — the priors that seed branch
probabilities in the Outcome DAG.

Shared by the graph endpoint and case creation so both derive branch priors
the same way `api/insights.py` derives `share_of_decisions`: count how each
scenario's past cases actually resolved.
"""
from __future__ import annotations

from typing import Callable


def decision_history_provider(database) -> Callable[[str], dict[str, float]]:
    """Return `scenario_id -> {decision_kind: count}` backed by the cases table."""
    from sqlalchemy import func, select

    from .persistence.db import CaseRow

    def provider(scenario_id: str) -> dict[str, float]:
        with database.session() as session:
            rows = session.execute(
                select(CaseRow.decision_kind, func.count(CaseRow.case_id))
                .where(CaseRow.scenario_id == scenario_id)
                .where(CaseRow.decision_kind.is_not(None))
                .group_by(CaseRow.decision_kind)
            ).all()
        return {kind: float(n) for kind, n in rows if kind}

    return provider
