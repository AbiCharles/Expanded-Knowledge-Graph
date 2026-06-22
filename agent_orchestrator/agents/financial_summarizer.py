"""Financial Impact Summarizer sub-agent.

Produces the dollar roll-up the demo closes on: total revenue at
risk, total OTD-penalty exposure per day, and a worst-case
days-to-mitigate window (a configurable demo constant; production
would derive this from supplier-lead-time data).
"""
from __future__ import annotations

from .distribution_optimizer import PROGRAM_STAKE

AGENT_ID = "financial_summarizer"
AGENT_NAME = "Financial Impact Summarizer"

# Worst-case days before OTD penalties trigger if no alternate supply
# is in place. Hard-coded; production reads from contract metadata.
DAYS_TO_MITIGATE = 14


def summarize(programs: list[dict]) -> dict:
    total_revenue_m = 0.0
    total_otd_k = 0.0
    breakdown: list[dict] = []
    for p in programs:
        pid = p.get("program_id") or ""
        meta = PROGRAM_STAKE.get(pid, {})
        rev = float(meta.get("revenue_usd_m", 0.0))
        otd = float(meta.get("otd_penalty_usd_k_per_day", 0.0))
        total_revenue_m += rev
        total_otd_k += otd
        breakdown.append(
            {
                "program_id": pid,
                "name": p.get("name") or meta.get("label") or pid,
                "revenue_usd_m": rev,
                "otd_penalty_usd_k_per_day": otd,
            }
        )
    worst_case_penalty_usd_m = (total_otd_k * DAYS_TO_MITIGATE) / 1000.0
    return {
        "total_revenue_at_risk_usd_m": total_revenue_m,
        "total_otd_penalty_usd_k_per_day": total_otd_k,
        "days_to_mitigate_worst_case": DAYS_TO_MITIGATE,
        "worst_case_penalty_usd_m": round(worst_case_penalty_usd_m, 2),
        "breakdown": breakdown,
        "headline": (
            f"${total_revenue_m:.0f}M revenue at risk across "
            f"{len(breakdown)} program(s) · "
            f"${total_otd_k:.0f}k/day OTD penalty exposure · "
            f"worst-case ${worst_case_penalty_usd_m:.1f}M in penalties "
            f"over {DAYS_TO_MITIGATE} days of unmitigated slip."
        ),
    }
