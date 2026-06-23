"""Run orchestration — drives the scripted investigation + sub-agents.

One `AgentRun` represents one click of "Start investigation" on the
frontend. The run owns a bounded async queue (`events`) that the SSE
endpoint drains to push events to the connected client. The flow:

  1. risk_monitor emits a synthetic Chapter-11 detection
  2. supplier_assurance acknowledges + opens an investigation
  3. fabric_client.fetch_subgraph(SUP-021) → one HTTP call answers
     the next three questions (tier-1 buyers, programs at risk,
     alternate suppliers)
  4. sub-agents fan out in parallel (asyncio.gather)
  5. orchestrator emits a `run_completed` payload with the
     walk-through links the frontend renders as the Naresh handoff

Everything in the run is in-memory; on process restart prior runs
are gone (acceptable for tomorrow's demo).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

from .events import AgentEvent
from .fabric_client import (
    FabricClient,
    extract_alternates,
    extract_programs_at_risk,
    extract_tier1_buyers,
)
from .narrator import Narrator
from .agents import (
    risk_monitor,
    supplier_assurance,
    distribution_optimizer,
    alternate_outreach,
    program_manager_notifier,
    financial_summarizer,
)

log = logging.getLogger(__name__)

# Brief pauses between phases so the audience can read each card
# as it lands. Tunable for the demo — small enough that the run
# completes in well under a minute.
PAUSE_AFTER_NARRATION = 0.4
PAUSE_BETWEEN_STAGES = 0.7


class AgentRun:
    """One investigation run. Drives the scripted flow + emits events."""

    def __init__(self, *, fabric: FabricClient, narrator: Narrator) -> None:
        self.run_id = uuid.uuid4().hex[:12]
        self.fabric = fabric
        self.narrator = narrator
        # Unbounded queue is fine here — the run only emits ~25 events
        # and a slow consumer (SSE) drains them quickly.
        self.events: asyncio.Queue[Optional[AgentEvent]] = asyncio.Queue()
        self.done = False

    async def emit(self, event: AgentEvent) -> None:
        await self.events.put(event)

    async def _narrate(self, *, agent_name: str, finding: str, fallback: str) -> None:
        text = await self.narrator.narrate(
            agent_name=agent_name, finding=finding, fallback=fallback
        )
        await self.emit(
            AgentEvent(
                type="agent_thinking",
                agent_id=_agent_id_from_name(agent_name),
                payload={"text": text, "finding": finding},
            )
        )
        await asyncio.sleep(PAUSE_AFTER_NARRATION)

    # ------------------------------------------------------------------
    # Main flow
    # ------------------------------------------------------------------
    async def run(self) -> None:
        try:
            await self._run_inner()
        except Exception as exc:  # noqa: BLE001
            log.exception("agent run %s failed", self.run_id)
            await self.emit(
                AgentEvent(
                    type="error",
                    agent_id="orchestrator",
                    payload={"message": str(exc)},
                )
            )
        finally:
            self.done = True
            # Sentinel so the SSE stream knows to close cleanly.
            await self.events.put(None)

    async def _run_inner(self) -> None:
        # ---- Step 0: News-source feed detected the Chapter 11 ------
        # This card lands FIRST so the audience sees that the agent
        # didn't decide to act out of nowhere — a real-world news
        # signal triggered it. The Risk Monitor card on the next
        # step explicitly cites this article.
        news = risk_monitor.news_source()
        await self.emit(
            AgentEvent(
                type="news_source_detected",
                agent_id="news_feed",
                payload={
                    "agent_name": "News Feed Monitor",
                    **news,
                },
            )
        )
        await asyncio.sleep(PAUSE_BETWEEN_STAGES)

        # ---- Step 1: Risk Monitor ----------------------------------
        risk = risk_monitor.detect_active_risk()
        await self.emit(
            AgentEvent(
                type="risk_detected",
                agent_id=risk_monitor.AGENT_ID,
                payload={
                    "agent_name": risk_monitor.AGENT_NAME,
                    "supplier_id": risk["supplier_id"],
                    "supplier_name": risk["supplier_name"],
                    "event": risk["event"],
                    "event_date": risk["event_date"],
                    "severity": risk["severity"],
                    "summary": risk["summary"],
                    # Pin the news article that caused this escalation
                    # so the UI can render a dashed connector back to
                    # the news_source_detected card.
                    "triggered_by_source": news["source"],
                    "triggered_by_headline": news["headline"],
                },
            )
        )
        await asyncio.sleep(PAUSE_BETWEEN_STAGES)

        # ---- Step 2: Supplier Assurance acks + opens investigation -
        await self.emit(
            AgentEvent(
                type="investigation_started",
                agent_id=supplier_assurance.AGENT_ID,
                payload={
                    "agent_name": supplier_assurance.AGENT_NAME,
                    "scope": (
                        "Scope: scope exposure across the customer's "
                        "tier-1 buyers, the affected POs/programs, and "
                        "qualified alternate suppliers."
                    ),
                    "anchor_supplier_id": risk["supplier_id"],
                },
            )
        )
        await self._narrate(
            agent_name=supplier_assurance.AGENT_NAME,
            finding=(
                f"Risk monitor escalated: {risk['supplier_name']} "
                f"({risk['supplier_id']}) filed {risk['event']} on "
                f"{risk['event_date']}. Need tier-1 exposure, program "
                f"impact, and alternate suppliers."
            ),
            fallback=(
                f"Opening investigation. Will pull tier-1 exposure, "
                f"program impact, and alternates for "
                f"{risk['supplier_id']} from the Knowledge Fabric."
            ),
        )

        # ---- Step 3-5: Single fabric call answers three questions --
        await self.emit(
            AgentEvent(
                type="fabric_query",
                agent_id=supplier_assurance.AGENT_ID,
                payload={
                    "agent_name": supplier_assurance.AGENT_NAME,
                    "endpoint": "/api/graph/subgraph",
                    "request": {"supplier_id": risk["supplier_id"], "depth": 4},
                    "description": (
                        "Walking the supply network: tier-1 buyers + "
                        "PO/Product/Program impact chains + alternate "
                        "supplier candidates."
                    ),
                },
                fabric_link=self.fabric.graph_url_for_supplier(risk["supplier_id"]),
            )
        )

        try:
            subgraph = await self.fabric.fetch_subgraph(
                risk["supplier_id"], depth=4
            )
        except Exception as exc:  # noqa: BLE001
            await self.emit(
                AgentEvent(
                    type="error",
                    agent_id=supplier_assurance.AGENT_ID,
                    payload={
                        "message": (
                            f"Fabric unreachable: {exc}. Investigation halted."
                        ),
                    },
                )
            )
            return

        await self.emit(
            AgentEvent(
                type="fabric_response",
                agent_id=supplier_assurance.AGENT_ID,
                payload={
                    "endpoint": "/api/graph/subgraph",
                    "stats": subgraph.get("stats", {}),
                    "node_count": len(subgraph.get("nodes") or []),
                    "edge_count": len(subgraph.get("edges") or []),
                },
                # Open the Network tab — the response IS the network.
                fabric_link=self.fabric.aeronova_view_url("graph"),
            )
        )
        await asyncio.sleep(PAUSE_BETWEEN_STAGES)

        tier1 = extract_tier1_buyers(subgraph, risk["supplier_id"])
        programs = extract_programs_at_risk(subgraph)
        alternates = extract_alternates(subgraph, risk["supplier_id"])

        await self.emit(
            AgentEvent(
                type="tier1_buyers_found",
                agent_id=supplier_assurance.AGENT_ID,
                payload={
                    "agent_name": supplier_assurance.AGENT_NAME,
                    "count": len(tier1),
                    "buyers": tier1,
                },
                # Open Network tab with the tier-1 buyer ids "called out"
                # (highlighted with a glow class on the matching nodes).
                fabric_link=self.fabric.aeronova_view_url(
                    "graph",
                    focus_ids=[b.get("supplier_id") for b in tier1 if b.get("supplier_id")],
                ),
            )
        )
        await self._narrate(
            agent_name=supplier_assurance.AGENT_NAME,
            finding=(
                f"Fabric returned {len(tier1)} tier-1 buyer(s) that source "
                f"from {risk['supplier_id']}: "
                + (
                    ", ".join(b.get("name", "?") for b in tier1)
                    if tier1
                    else "(none — anchor has no direct tier-1 buyers)"
                )
                + "."
            ),
            fallback=(
                f"Identified {len(tier1)} tier-1 buyer(s) downstream of "
                f"{risk['supplier_id']}. Walking forward to the POs and "
                f"programs they feed."
            ),
        )

        await self.emit(
            AgentEvent(
                type="programs_at_risk_identified",
                agent_id=supplier_assurance.AGENT_ID,
                payload={
                    "agent_name": supplier_assurance.AGENT_NAME,
                    "count": len(programs),
                    "programs": programs,
                },
                # Open Network tab with the Program ids highlighted so
                # the audience sees exactly which terminals matter.
                fabric_link=self.fabric.aeronova_view_url(
                    "graph",
                    focus_ids=[p.get("program_id") for p in programs if p.get("program_id")],
                ),
            )
        )
        await self._narrate(
            agent_name=supplier_assurance.AGENT_NAME,
            finding=(
                f"Program-impact chain surfaced {len(programs)} program(s) "
                f"at risk: "
                + (
                    ", ".join(p.get("name", "?") for p in programs)
                    if programs
                    else "(none — chain did not reach any Program node)"
                )
                + "."
            ),
            fallback=(
                f"{len(programs)} downstream program(s) exposed if "
                f"shipments slip."
            ),
        )

        await self.emit(
            AgentEvent(
                type="alternates_surfaced",
                agent_id=supplier_assurance.AGENT_ID,
                payload={
                    "agent_name": supplier_assurance.AGENT_NAME,
                    "count": len(alternates),
                    "alternates": alternates,
                },
                # Decision pathways tab — green chain (Ironcrest) vs red
                # chain (Stillwater) tells the proposed-vs-avoid story
                # better than the topology view.
                fabric_link=self.fabric.aeronova_view_url("pathways"),
            )
        )
        await self._narrate(
            agent_name=supplier_assurance.AGENT_NAME,
            finding=(
                f"Alternate-supplier walk found {len(alternates)} "
                f"candidate(s): "
                + (
                    ", ".join(
                        f"{a.get('name', '?')} ({a.get('via', 'unknown')})"
                        for a in alternates
                    )
                    if alternates
                    else "(none — no JV partners or shared-parent siblings in graph)"
                )
                + "."
            ),
            fallback=(
                f"{len(alternates)} alternate supplier candidate(s) "
                f"identified. Handing off to sub-agents for outreach + "
                f"distribution analysis."
            ),
        )
        await asyncio.sleep(PAUSE_BETWEEN_STAGES)

        # ---- Step 6: spawn sub-agents in parallel ------------------
        await self.emit(
            AgentEvent(
                type="subagents_spawned",
                agent_id=supplier_assurance.AGENT_ID,
                payload={
                    "agent_name": supplier_assurance.AGENT_NAME,
                    "subagents": [
                        {"id": distribution_optimizer.AGENT_ID, "name": distribution_optimizer.AGENT_NAME},
                        {"id": alternate_outreach.AGENT_ID, "name": alternate_outreach.AGENT_NAME},
                        {"id": program_manager_notifier.AGENT_ID, "name": program_manager_notifier.AGENT_NAME},
                        {"id": financial_summarizer.AGENT_ID, "name": financial_summarizer.AGENT_NAME},
                    ],
                },
            )
        )

        # Each sub-agent emits its own started + completed events. They
        # run concurrently via asyncio.gather; small per-agent sleeps
        # stagger their stream timestamps so the UI cards land visibly
        # in parallel rather than all at once.
        results = await asyncio.gather(
            self._run_distribution_optimizer(programs),
            self._run_alternate_outreach(alternates),
            self._run_program_manager_notifier(programs),
            self._run_financial_summarizer(programs),
            return_exceptions=True,
        )
        summarized: dict = {}
        for r in results:
            if isinstance(r, BaseException):
                log.warning("sub-agent failed: %s", r)
                continue
            if isinstance(r, dict):
                summarized.update(r)

        # ---- Step 7: post findings to the fabric so the decision
        # pathways graph can overlay PM names + outreach status. ----
        # Module-top imports already cover program_manager_notifier;
        # a local import here would shadow the global and crash every
        # reference earlier in the function with UnboundLocalError.
        from datetime import datetime, timezone
        findings_payload = {
            "run_id": self.run_id,
            "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "program_managers": program_manager_notifier.PROGRAM_MANAGERS,
            "alternate_outreach": {
                "primary": [
                    {"supplier_id": p.get("supplier_id"), "name": p.get("name"), "via": p.get("via")}
                    for p in (summarized.get("alternate_outreach", {}).get("primary") or [])
                ],
                "blocked": [
                    {"supplier_id": b.get("supplier_id"), "name": b.get("name"), "via": b.get("via"), "reason": b.get("reason")}
                    for b in (summarized.get("alternate_outreach", {}).get("blocked") or [])
                ],
            },
        }
        await self.fabric.post_aeronova_findings(findings_payload)

        # ---- Step 8: run summary + walk-through links --------------
        walkthrough_links = [
            {
                "label": "Knowledge graph — supplier subgraph around SUP-021",
                "url": self.fabric.graph_url_for_supplier(risk["supplier_id"]),
            },
            {
                "label": "Aeronova case launch flow (manual walkthrough)",
                "url": self.fabric.aeronova_case_url(),
            },
        ]
        await self.emit(
            AgentEvent(
                type="run_completed",
                agent_id="orchestrator",
                payload={
                    "anchor_supplier_id": risk["supplier_id"],
                    "anchor_supplier_name": risk["supplier_name"],
                    "tier1_buyer_count": len(tier1),
                    "programs_at_risk_count": len(programs),
                    "alternate_count": len(alternates),
                    "summary": summarized,
                    "walkthrough_links": walkthrough_links,
                },
            )
        )

    # ------------------------------------------------------------------
    # Sub-agents
    # ------------------------------------------------------------------
    async def _run_distribution_optimizer(self, programs: list[dict]) -> dict:
        await self._subagent_started(
            distribution_optimizer.AGENT_ID, distribution_optimizer.AGENT_NAME
        )
        ranked = distribution_optimizer.rank_programs(programs)
        recommendation = distribution_optimizer.recommendation(ranked)
        await self._narrate(
            agent_name=distribution_optimizer.AGENT_NAME,
            finding=(
                "Ranked at-risk programs by revenue stake: "
                + ", ".join(
                    f"{r['name']} ${r['revenue_usd_m']:.0f}M" for r in ranked
                )
                + "."
            ),
            fallback=(
                "Allocating alternate capacity by revenue stake "
                "(largest first)."
            ),
        )
        await self.emit(
            AgentEvent(
                type="subagent_completed",
                agent_id=distribution_optimizer.AGENT_ID,
                payload={
                    "agent_name": distribution_optimizer.AGENT_NAME,
                    "ranked": ranked,
                    "recommendation": recommendation,
                },
            )
        )
        return {"distribution_optimizer": {"ranked": ranked, "recommendation": recommendation}}

    async def _run_alternate_outreach(self, alternates: list[dict]) -> dict:
        await self._subagent_started(
            alternate_outreach.AGENT_ID, alternate_outreach.AGENT_NAME
        )
        result = alternate_outreach.evaluate(alternates)
        blocked_names = [b["name"] for b in result["blocked"]]
        primary_names = [p["name"] for p in result["primary"]]
        await self._narrate(
            agent_name=alternate_outreach.AGENT_NAME,
            finding=(
                (
                    f"Outreach drafted for: {', '.join(primary_names)}. "
                    if primary_names
                    else "No alternates pass compliance. "
                )
                + (
                    f"Blocked: {', '.join(blocked_names)}."
                    if blocked_names
                    else ""
                )
            ),
            fallback=(
                "Outreach drafts ready. Compliance-blocked candidates "
                "skipped."
            ),
        )
        await self.emit(
            AgentEvent(
                type="subagent_completed",
                agent_id=alternate_outreach.AGENT_ID,
                payload={
                    "agent_name": alternate_outreach.AGENT_NAME,
                    "primary": result["primary"],
                    "blocked": result["blocked"],
                    "drafts": result["drafts"],
                },
                # Deep-link → fabric's Decision-pathways tab on the
                # Aeronova case. The audience sees the proposed swap
                # chain (Ironcrest in green) right next to the avoid
                # chain (Stillwater in red), with the program-impact
                # context the alternate selection was reasoned against.
                # Pathways > Network here because Network only shows
                # topology; Pathways shows topology + decision overlay.
                fabric_link=self.fabric.aeronova_view_url("pathways"),
            )
        )
        return {"alternate_outreach": result}

    async def _run_program_manager_notifier(self, programs: list[dict]) -> dict:
        await self._subagent_started(
            program_manager_notifier.AGENT_ID, program_manager_notifier.AGENT_NAME
        )
        notifications = program_manager_notifier.draft_notifications(programs)
        await self._narrate(
            agent_name=program_manager_notifier.AGENT_NAME,
            finding=(
                f"Drafted {len(notifications)} program-manager notification(s) "
                "naming the specific PO + revenue stake for each program."
            ),
            fallback=(
                f"{len(notifications)} per-program notification(s) drafted."
            ),
        )
        await self.emit(
            AgentEvent(
                type="subagent_completed",
                agent_id=program_manager_notifier.AGENT_ID,
                payload={
                    "agent_name": program_manager_notifier.AGENT_NAME,
                    "notifications": notifications,
                },
                # Deep-link → fabric's knowledge graph in Decision-pathways
                # mode, where the 3 Aeronova program terminals show their
                # revenue + OTD stakes. Audience sees the same numbers the
                # PM notifications cite.
                fabric_link=self.fabric.aeronova_view_url("pathways"),
            )
        )
        return {"program_manager_notifier": {"notifications": notifications}}

    async def _run_financial_summarizer(self, programs: list[dict]) -> dict:
        await self._subagent_started(
            financial_summarizer.AGENT_ID, financial_summarizer.AGENT_NAME
        )
        summary = financial_summarizer.summarize(programs)
        await self._narrate(
            agent_name=financial_summarizer.AGENT_NAME,
            finding=summary["headline"],
            fallback=summary["headline"],
        )
        await self.emit(
            AgentEvent(
                type="subagent_completed",
                agent_id=financial_summarizer.AGENT_ID,
                payload={
                    "agent_name": financial_summarizer.AGENT_NAME,
                    **summary,
                },
            )
        )
        return {"financial_summarizer": summary}

    async def _subagent_started(self, agent_id: str, agent_name: str) -> None:
        await self.emit(
            AgentEvent(
                type="subagent_started",
                agent_id=agent_id,
                payload={"agent_name": agent_name},
            )
        )
        # Stagger so the UI's parallel cards animate in visibly.
        await asyncio.sleep(0.3)


def _agent_id_from_name(name: str) -> str:
    return name.lower().replace(" ", "_")
