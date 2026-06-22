"""Risk Monitor agent — first link in the chain.

In production this would be a poll on a SQL view that watches for
new Chapter-11 / qualification-lapse / SDN-listing events. For the
demo it's synthetic: a fixed detection record that names Northwind
Forge (SUP-021) so the rest of the flow has something concrete to
act on.

Kept as a module (not just a constant) so a V2 can swap in a real
detector without changing the orchestrator's call site.
"""
from __future__ import annotations

AGENT_ID = "risk_monitor"
AGENT_NAME = "Risk Monitor"


def detect_active_risk() -> dict[str, str]:
    """Return the single active risk event for the demo run.

    Hardcoded to the Aeronova narrative: Northwind Forge filed
    Chapter 11 on 2026-06-18. The orchestrator reads `supplier_id`
    to drive the rest of the investigation.
    """
    return {
        "supplier_id": "SUP-021",
        "supplier_name": "Northwind Forge & Castings",
        "event": "chapter_11_filed",
        "event_date": "2026-06-18",
        "severity": "high",
        "summary": (
            "Tier-2 supplier Northwind Forge & Castings (SUP-021) filed "
            "for Chapter 11 protection on 2026-06-18. Exposure not yet "
            "scoped — escalating to Supplier Assurance for investigation."
        ),
    }
