"""
End-to-end example: SC-TC-007 (Human approval for trade override) routes a
proposal into the HITL Context Service.

Flow demonstrated:
  1. Agent intake binder seeds with policy + actor scope
  2. Agent proposes a trade override action
  3. Proposal binder attaches: target product, prior sanctions screening result,
     contract-of-record
  4. Review binder assembles: all of the above + applicable SOPs +
     prior similar overrides
  5. Sync transport surfaces the Adaptive Card and captures decision
  6. Lineage shows the full chain
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tcs_hitl_context import (
    AgentAction,
    HITLContextService,
    InMemoryLineageRecorder,
    KnowledgeFact,
    KnowledgeQuery,
    KnowledgeRef,
    Stage,
    StageContext,
    SyncInProcessTransport,
    TeamsAdaptiveCardSurface,
    TransportMode,
    TruthSourceMode,
)


# =============================================================================
# Reference binder implementations (illustrative — production binders query KF)
# =============================================================================

class PolicyAndScopeAgentBinder:
    """Seeds the agent with policy + actor scope from KF."""

    def bind(self, agent_id, scenario):
        facts = [
            KnowledgeFact(
                ref=KnowledgeRef(
                    source="kf:graph",
                    ontology_type="Policy",
                    id="POL-TC-OVERRIDE-2026-Q2",
                    version="2026.04",
                    uri="https://kf.tcs/policy/POL-TC-OVERRIDE-2026-Q2",
                ),
                payload={
                    "title": "Trade compliance override policy",
                    "rule": "Any override of a critical trade-compliance guardrail "
                            "requires named compliance officer approval; not "
                            "delegable to agents.",
                },
                fetched_by="kf_resolver",
            ),
            KnowledgeFact(
                ref=KnowledgeRef(
                    source="iam:scopes",
                    ontology_type="ActorScope",
                    id=agent_id,
                    uri=f"https://iam.tcs/actors/{agent_id}",
                ),
                payload={
                    "agent_id": agent_id,
                    "scopes": ["sc.read", "sc.propose", "sc.execute_after_review"],
                    "max_commitment": 250_000,
                },
                fetched_by="iam_resolver",
            ),
        ]
        return StageContext(
            stage=Stage.AGENT_INTAKE,
            facts=facts,
            queries_issued=[
                KnowledgeQuery(
                    ontology_type="Policy",
                    filters={"domain": "trade_compliance", "active": True},
                    requested_by="agent_intake_binder",
                    purpose="Surface active TC override policy",
                ),
            ],
            bound_by="PolicyAndScopeAgentBinder/1.0",
        )


class TradeOverrideProposalBinder:
    """Binds product, prior sanctions screening, and contract-of-record."""

    def bind(self, action):
        product_id = action.payload.get("product_id")
        counterparty = action.payload.get("counterparty_name", "unknown")
        contract_id = action.payload.get("contract_id")

        facts = [
            KnowledgeFact(
                ref=KnowledgeRef(
                    source="erp:material_master",
                    ontology_type="Product",
                    id=product_id,
                    uri=f"https://erp.tcs/products/{product_id}",
                ),
                payload={"product_id": product_id, "eccn": "5A002", "hts": "8517.62.00"},
                fetched_by="erp_resolver",
            ),
            KnowledgeFact(
                ref=KnowledgeRef(
                    source="governance:guardrail_results",
                    ontology_type="GuardrailResult",
                    id=f"GR-{action.action_id}-SC-TC-001",
                    uri=f"https://governance.tcs/results/GR-{action.action_id}",
                ),
                payload={
                    "guardrail_id": "SC-TC-001",
                    "decision": "block",
                    "reason": f"Sanctions hit on '{counterparty}'",
                    "score": 0.94,
                },
                fetched_by="governance_resolver",
                truth_mode=TruthSourceMode.HYBRID,
            ),
            KnowledgeFact(
                ref=KnowledgeRef(
                    source="contract_mgmt",
                    ontology_type="Contract",
                    id=contract_id,
                    uri=f"https://contracts.tcs/{contract_id}",
                ),
                payload={"contract_id": contract_id, "incoterm": "DDP", "value": 480_000},
                fetched_by="contract_resolver",
            ),
        ]
        return StageContext(
            stage=Stage.PROPOSAL,
            facts=facts,
            bound_by="TradeOverrideProposalBinder/1.0",
            notes="Bound to product master, originating guardrail block, contract.",
        )


class TradeOverrideReviewBinder:
    """Adds SOP and prior similar overrides to the reviewer evidence."""

    def bind(self, action, prior):
        facts = [
            KnowledgeFact(
                ref=KnowledgeRef(
                    source="kf:graph",
                    ontology_type="SOP",
                    id="SOP-TC-OVERRIDE-001",
                    uri="https://kf.tcs/sop/SOP-TC-OVERRIDE-001",
                ),
                payload={"title": "Trade override standard operating procedure",
                         "checklist": ["Verify license", "Confirm end-use",
                                       "Document rationale", "Two-person rule"]},
                fetched_by="kf_resolver",
            ),
            KnowledgeFact(
                ref=KnowledgeRef(
                    source="governance:case_history",
                    ontology_type="PriorOverride",
                    id="PR-2026-Q1-088",
                    uri="https://governance.tcs/cases/PR-2026-Q1-088",
                ),
                payload={
                    "case_id": "PR-2026-Q1-088",
                    "outcome": "rejected",
                    "rationale": "End-user could not be verified",
                },
                fetched_by="case_history_resolver",
                confidence=0.78,  # similarity score
            ),
        ]
        return StageContext(
            stage=Stage.REVIEW,
            facts=facts,
            bound_by="TradeOverrideReviewBinder/1.0",
            notes="Reviewer package: SOP + prior similar overrides.",
        )


# =============================================================================
# Demo run
# =============================================================================

def _fake_reviewer(card_payload):
    """Stand-in for a real Teams card response — auto-rejects this case."""
    return {
        "decision": "reject",
        "ticket_id": "set-by-transport",
        "reviewer_id": "compliance.officer.kchen",
        "rationale": "Sanctions hit confirmed; override denied per SOP-TC-OVERRIDE-001.",
    }


def main():
    # Wire components
    surface = TeamsAdaptiveCardSurface()
    transport = SyncInProcessTransport(surface=surface, decision_callable=_fake_reviewer)
    lineage = InMemoryLineageRecorder()

    service = HITLContextService(
        agent_binder=PolicyAndScopeAgentBinder(),
        proposal_binder=TradeOverrideProposalBinder(),
        review_binder=TradeOverrideReviewBinder(),
        transport=transport,
        lineage=lineage,
    )

    # Stage 1: open case + bind agent intake
    ctx = service.open_case(
        agent_id="agent-trade-01",
        scenario={"domain": "supply_chain", "intent": "trade_override"},
        transport_mode=TransportMode.SYNC,
    )

    # Stage 2: agent proposes an override action
    action = AgentAction(
        action_id="ACT-OVR-9001",
        action_type="trade_override",
        actor_id="agent-trade-01",
        payload={
            "originating_guardrail_id": "SC-TC-001",
            "product_id": "P-EL-9001",
            "counterparty_name": "Sanctioned Pharma Holdings",
            "contract_id": "K-2026-0182",
            "override_reason": "Customer claims license; need verification.",
        },
    )
    service.attach_proposal(ctx, action)

    # Stage 3: submit for review
    ticket = service.submit_for_review(ctx)

    # Stage 4: collect decision
    decision = service.collect_decision(ctx, ticket.ticket_id)

    # ---- Output ----
    print(f"Case: {ctx.case_id}")
    print(f"Ticket: {ticket.ticket_id}  ({ticket.transport.value})")
    print(f"Decision: {decision.decision.value}  by {decision.reviewer_id}")
    print(f"Rationale: {decision.rationale}\n")

    print("Stages bound:")
    for stage, sc in ctx.stages.items():
        print(f"  {stage.value:14s} — {len(sc.facts)} fact(s) — {sc.bound_by}")

    print("\nLineage:")
    for ev in ctx.lineage:
        print(f"  #{ev.sequence:02d} {ev.stage.value:13s} {ev.actor:30s} "
              f"{ev.action:10s} — {ev.detail}")

    print("\nKnowledge refs across all stages:")
    for f in ctx.all_facts():
        print(f"  [{f.ref.source}] {f.ref.ontology_type}:{f.ref.id} "
              f"(truth={f.truth_mode.value})")

    # Show a tiny slice of the rendered card for confirmation
    rendered = surface.render(ctx)
    print(f"\nCard schema: {rendered['type']} v{rendered['version']} — "
          f"{len(rendered['body'])} body element(s), "
          f"{len(rendered['actions'])} action(s)")


if __name__ == "__main__":
    main()
