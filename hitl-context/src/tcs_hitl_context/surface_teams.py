"""
Reference reviewer surface — Teams Adaptive Card v1.5.

Renders the KnowledgeContext into a card payload Teams (or Outlook Actionable
Messages, ServiceNow with the right adapter) can display. Web UI fallback uses
the same payload — the front-end picks whichever sections it can render.
"""
from __future__ import annotations

from typing import Any

from .models import (
    KnowledgeContext,
    KnowledgeFact,
    ReviewDecision,
    ReviewDecisionKind,
    Stage,
)


class TeamsAdaptiveCardSurface:
    """Renders KnowledgeContext → Adaptive Card; parses card responses → ReviewDecision."""

    name = "teams_adaptive_card_v1"

    def render(self, ctx: KnowledgeContext) -> dict[str, Any]:
        # Headline
        body: list[dict[str, Any]] = [
            {
                "type": "TextBlock",
                "text": f"Action review · {ctx.action.action_type}",
                "weight": "Bolder",
                "size": "Large",
            },
            {
                "type": "TextBlock",
                "text": f"Case: {ctx.case_id} · Agent: {ctx.agent_id}",
                "isSubtle": True,
                "size": "Small",
                "wrap": True,
            },
            {"type": "TextBlock", "text": "Proposed action", "weight": "Bolder"},
            self._fact_block({
                "action_id": ctx.action.action_id,
                "action_type": ctx.action.action_type,
                "actor_id": ctx.action.actor_id,
                **ctx.action.payload,
            }),
        ]

        # Stage-by-stage knowledge sections
        for stage_label, stage in [
            ("Agent intake context", Stage.AGENT_INTAKE),
            ("Proposal-bound knowledge", Stage.PROPOSAL),
            ("Review evidence", Stage.REVIEW),
        ]:
            sc = ctx.stages.get(stage)
            if not sc or not sc.facts:
                continue
            body.append({"type": "TextBlock", "text": stage_label, "weight": "Bolder"})
            for fact in sc.facts:
                body.append(self._fact_card(fact))

        # Lineage summary (collapsed by default)
        if ctx.lineage:
            body.append({
                "type": "TextBlock", "text": "Lineage",
                "weight": "Bolder", "spacing": "Medium",
            })
            for ev in ctx.lineage[-8:]:  # last 8 events fit comfortably
                body.append({
                    "type": "TextBlock",
                    "size": "Small",
                    "isSubtle": True,
                    "wrap": True,
                    "text": (
                        f"#{ev.sequence:02d} · {ev.stage.value} · "
                        f"{ev.actor} · {ev.action} — {ev.detail or ''}"
                    ),
                })

        # Decision actions
        actions = [
            {
                "type": "Action.Submit", "title": "Approve",
                "data": {"decision": "approve", "ticket_id": ctx.ticket.ticket_id if ctx.ticket else None},
                "style": "positive",
            },
            {
                "type": "Action.Submit", "title": "Reject",
                "data": {"decision": "reject", "ticket_id": ctx.ticket.ticket_id if ctx.ticket else None},
                "style": "destructive",
            },
            {
                "type": "Action.Submit", "title": "Need more info",
                "data": {"decision": "request_more_info", "ticket_id": ctx.ticket.ticket_id if ctx.ticket else None},
            },
        ]

        return {
            "type": "AdaptiveCard",
            "version": "1.5",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "body": body,
            "actions": actions,
        }

    def parse_decision(self, payload: dict[str, Any]) -> ReviewDecision:
        kind_raw = payload.get("decision", "request_more_info")
        return ReviewDecision(
            ticket_id=payload.get("ticket_id", ""),
            case_id=payload.get("case_id", ""),
            decision=ReviewDecisionKind(kind_raw),
            reviewer_id=payload.get("reviewer_id", "unknown"),
            rationale=payload.get("rationale", ""),
        )

    # ---- helpers ------------------------------------------------------------
    def _fact_card(self, fact: KnowledgeFact) -> dict[str, Any]:
        ref = fact.ref
        title = f"{ref.ontology_type} · {ref.id}"
        sub = f"{ref.source}" + (f" · v{ref.version}" if ref.version else "")
        block: dict[str, Any] = {
            "type": "Container",
            "style": "emphasis",
            "spacing": "Small",
            "items": [
                {"type": "TextBlock", "text": title, "weight": "Bolder", "wrap": True},
                {"type": "TextBlock", "text": sub, "isSubtle": True, "size": "Small"},
                self._fact_block(fact.payload),
            ],
        }
        if ref.uri:
            block["selectAction"] = {
                "type": "Action.OpenUrl", "title": "Open source", "url": ref.uri,
            }
        return block

    def _fact_block(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "FactSet",
            "facts": [{"title": str(k), "value": str(v)} for k, v in payload.items()],
        }
