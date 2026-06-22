"""Alternate Outreach sub-agent.

Drafts outreach messages to candidate alternate suppliers. Carries a
small qualification lookup table so the agent can flag Stillwater's
lapsed certification (the "trap" alternate from the deck) as a
compliance block before any outreach goes out, and recommend
Ironcrest (the clean JV partner) as primary contact.
"""
from __future__ import annotations

AGENT_ID = "alternate_outreach"
AGENT_NAME = "Alternate Outreach"

# Per-alternate metadata. Keys are supplier_id; values come from the
# Neo4j seed (share/tcs_kf_graph_data/seed_neo4j.cypher). Hard-coded
# here so the agent doesn't need a second fabric round-trip; the
# narrator still tells the audience these came from the governed
# knowledge layer.
ALTERNATE_META: dict[str, dict] = {
    "SUP-022": {
        "name": "Stillwater Alloys",
        "qualification_status": "lapsed",
        "qualification_expired_on": "2026-04-15",
        "reliability_score": 0.74,
        "country": "CZ",
    },
    "SUP-023": {
        "name": "Ironcrest Metalworks",
        "qualification_status": "qualified",
        "qualification_expires_on": "2028-03-15",
        "reliability_score": 0.91,
        "country": "DE",
    },
}


def evaluate(alternates: list[dict]) -> dict:
    """Return {primary, blocked, drafts} — what outreach to send + skip.

    Walks the alternates surfaced by the fabric, joins with the
    metadata table above to flag compliance blocks, and builds a
    per-supplier outreach draft.
    """
    primary: list[dict] = []
    blocked: list[dict] = []
    drafts: list[dict] = []

    for alt in alternates:
        sid = alt.get("supplier_id") or ""
        meta = ALTERNATE_META.get(sid, {})
        name = alt.get("name") or meta.get("name") or sid
        via = alt.get("via", "")
        qual = meta.get("qualification_status", "unknown")
        reliability = meta.get("reliability_score")

        if qual == "lapsed":
            blocked.append(
                {
                    "supplier_id": sid,
                    "name": name,
                    "reason": (
                        f"qualification lapsed — expired "
                        f"{meta.get('qualification_expired_on', '?')}"
                    ),
                    "via": via,
                }
            )
            continue

        # Build a short outreach draft. Production would template this
        # against the customer's tone-of-voice and route through Slack/
        # email; for the demo it's just text.
        draft = (
            f"Subject: Urgent — Northwind Forge supply continuity (Aeronova)\n\n"
            f"Hello {name} team,\n\n"
            f"Our Northwind Forge & Castings (SUP-021) tier-2 supply has "
            f"been disrupted by their 2026-06-18 Chapter 11 filing. We're "
            f"reaching out as a vetted alternate ({via}, qualification "
            f"{qual}"
            + (
                f", reliability {reliability:.2f}"
                if isinstance(reliability, (int, float))
                else ""
            )
            + f") to discuss expedited supply across three Aeronova "
            f"programs (Mirage / Viper / Comet). Can we schedule a call "
            f"in the next 24 hours to confirm capacity + lead times?\n\n"
            f"— Aeronova Supply Assurance"
        )
        primary.append(
            {
                "supplier_id": sid,
                "name": name,
                "via": via,
                "qualification_status": qual,
                "reliability_score": reliability,
            }
        )
        drafts.append({"to": name, "supplier_id": sid, "body": draft})

    return {"primary": primary, "blocked": blocked, "drafts": drafts}
