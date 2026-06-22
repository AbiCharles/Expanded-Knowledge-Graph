"""Distribution Optimizer sub-agent.

Ranks the at-risk programs by revenue stake and recommends the
allocation order if alternate-supplier capacity is constrained.
For the Aeronova demo this is deterministic: Mirage > Viper > Comet
by revenue. The "thinking" is short LLM narration the orchestrator
calls separately.
"""
from __future__ import annotations

AGENT_ID = "distribution_optimizer"
AGENT_NAME = "Distribution Optimizer"

# Per-program stake metadata. Keys match the Program ids/labels surfaced
# by the fabric subgraph; values come from the supply_chain ontology
# mappings file. Kept here (not fetched live) so the agent runs
# deterministically even if the fabric returns shortened labels.
PROGRAM_STAKE: dict[str, dict[str, float | str]] = {
    "PRG-AERO-MIRAGE": {
        "label": "Mirage Avionics platform",
        "customer": "Aeronova",
        "revenue_usd_m": 48.0,
        "otd_penalty_usd_k_per_day": 220.0,
    },
    "PRG-AERO-VIPER": {
        "label": "Viper UAV sustainment",
        "customer": "Aeronova",
        "revenue_usd_m": 11.0,
        "otd_penalty_usd_k_per_day": 85.0,
    },
    "PRG-AERO-COMET": {
        "label": "Comet satellite payload",
        "customer": "Aeronova",
        "revenue_usd_m": 9.0,
        "otd_penalty_usd_k_per_day": 60.0,
    },
}


def rank_programs(programs: list[dict]) -> list[dict]:
    """Sort the at-risk programs by revenue stake, descending.

    Programs unknown to the catalog above land at the bottom with
    zero stake (so the demo still completes if the fabric ever
    surfaces an unexpected program).
    """
    enriched: list[dict] = []
    for p in programs:
        pid = p.get("program_id") or ""
        meta = PROGRAM_STAKE.get(pid, {})
        enriched.append(
            {
                "program_id": pid,
                "name": p.get("name") or meta.get("label") or pid,
                "revenue_usd_m": meta.get("revenue_usd_m", 0.0),
                "otd_penalty_usd_k_per_day": meta.get("otd_penalty_usd_k_per_day", 0.0),
            }
        )
    enriched.sort(
        key=lambda r: (-float(r["revenue_usd_m"]), -float(r["otd_penalty_usd_k_per_day"]))
    )
    return enriched


def recommendation(ranked: list[dict]) -> str:
    """One-line allocation recommendation for the UI."""
    if not ranked:
        return "No at-risk programs identified — nothing to prioritize."
    order = " → ".join(r["name"] for r in ranked)
    top = ranked[0]
    return (
        f"Recommend allocating alternate capacity in this order: {order}. "
        f"{top['name']} carries the largest stake "
        f"(${top['revenue_usd_m']:.0f}M revenue, "
        f"${top['otd_penalty_usd_k_per_day']:.0f}k/day OTD penalty)."
    )
