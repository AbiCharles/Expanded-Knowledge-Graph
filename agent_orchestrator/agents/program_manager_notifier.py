"""Program Manager Notifier sub-agent.

Drafts a targeted notification to each affected program manager
naming the specific PO + revenue at stake. No real delivery — for
the demo the drafts just stream to the UI.
"""
from __future__ import annotations

from .distribution_optimizer import PROGRAM_STAKE

AGENT_ID = "program_manager_notifier"
AGENT_NAME = "Program Manager Notifier"

# Hard-coded PM mapping. Production would resolve via an org-chart
# service; for the demo the names match the lineage actor strings
# used elsewhere in the demo.
PROGRAM_MANAGERS: dict[str, str] = {
    "PRG-AERO-MIRAGE": "rachel.tan @ Aeronova (Mirage)",
    "PRG-AERO-VIPER": "marcus.iglesias @ Aeronova (Viper)",
    "PRG-AERO-COMET": "hannah.okafor @ Aeronova (Comet)",
}


def draft_notifications(programs: list[dict]) -> list[dict]:
    """Per-program draft message naming the specific stake."""
    out: list[dict] = []
    for p in programs:
        pid = p.get("program_id") or ""
        meta = PROGRAM_STAKE.get(pid, {})
        pm = PROGRAM_MANAGERS.get(pid, "program lead")
        name = p.get("name") or meta.get("label") or pid
        revenue = meta.get("revenue_usd_m", 0.0)
        otd = meta.get("otd_penalty_usd_k_per_day", 0.0)
        body = (
            f"Subject: Supply-assurance update — {name}\n\n"
            f"Hello,\n\n"
            f"Northwind Forge & Castings (SUP-021) filed Chapter 11 on "
            f"2026-06-18. Your program ({name}) is on the impact list — "
            f"revenue stake ${revenue:.0f}M, OTD penalty exposure "
            f"${otd:.0f}k/day if shipments slip.\n\n"
            f"Supply Assurance is in flight: alternate supplier outreach "
            f"is underway (Ironcrest Metalworks identified as primary "
            f"candidate). Distribution Optimizer will publish allocation "
            f"order shortly. No PM action required yet; this is the "
            f"heads-up.\n\n"
            f"— Supplier Assurance Orchestrator"
        )
        out.append(
            {"program_id": pid, "program_name": name, "to": pm, "body": body}
        )
    return out
