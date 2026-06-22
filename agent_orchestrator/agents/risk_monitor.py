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


def news_source() -> dict[str, str]:
    """The (mock) news clipping that triggered THIS run.

    Shaped as a Reuters wire-story so the audience sees the chain of
    custody: news feed → Risk Monitor agent → Supplier Assurance.
    For the demo the data is hand-authored; production would have a
    poll on a real news API + a classifier deciding whether each
    article is supply-relevant.
    """
    return {
        "source": "Reuters",
        "section": "Aerospace & Defense",
        "headline": (
            "Czech tier-2 aerospace forging supplier files for Chapter 11 "
            "protection"
        ),
        "byline": "Reuters Manufacturing Desk",
        "published_at": "2026-06-18T08:14:00Z",
        "url": "#news/northwind-forge-chapter-11",  # mock — no real link
        "lede": (
            "Northwind Forge & Castings, a privately-held Czech supplier of "
            "aerospace-grade forged stock and cast blanks to multiple US "
            "prime contractors, filed for Chapter 11 bankruptcy protection "
            "in Prague yesterday, citing accelerating creditor pressure "
            "following a failed refinancing round. Three downstream tier-1 "
            "buyers are expected to be impacted; the company did not "
            "respond to a request for comment."
        ),
        "matched_entity": "Northwind Forge & Castings",
        "matched_supplier_id": "SUP-021",
        "relevance_score": 0.94,
    }


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
