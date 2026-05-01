"""
Comprehensive verification of the tcs_hitl_context package.

Covers:
  1. Module imports and __all__ surface
  2. Pydantic model construction and validation (positive + negative)
  3. Sync transport — full round-trip with approve / reject / request_more_info
  4. Async transport — submit, poll-before-decide returns None, poll-after-decide
  5. Lineage — append-only, sequence ordering, knowledge refs preserved
  6. JSON serialization / deserialization round-trip (the contract claim)
  7. Surface — render produces valid Adaptive Card payload
  8. Service — full open_case → attach_proposal → submit → collect for both modes
  9. Edge cases: missing decision (poll returns None), cancel
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Counters
PASSED = 0
FAILED = 0
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        msg = f"  FAIL  {name}" + (f" — {detail}" if detail else "")
        FAILURES.append(msg)
        print(msg)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# =============================================================================
# 1. Imports
# =============================================================================
section("1. Imports and __all__ surface")

import tcs_hitl_context as hc

expected_exports = [
    "AgentAction", "KnowledgeContext", "KnowledgeFact", "KnowledgeQuery",
    "KnowledgeRef", "LineageEvent", "ReviewDecision", "ReviewDecisionKind",
    "ReviewTicket", "Stage", "StageContext", "TransportMode", "TruthSourceMode",
    "AgentIntakeBinder", "HITLTransport", "KnowledgeResolver",
    "KnowledgeResolverRegistry", "LineageRecorder", "ProposalBinder",
    "ReviewBinder", "ReviewerSurface",
    "HITLContextService", "InMemoryLineageRecorder", "TeamsAdaptiveCardSurface",
    "SyncInProcessTransport", "AsyncQueueTransport",
    "OutboundQueue", "DecisionStore",
    "make_event",
]
for name in expected_exports:
    check(f"export: {name}", hasattr(hc, name))

check("__version__ defined", hc.__version__ == "0.1.0")


# =============================================================================
# 2. Pydantic model validation
# =============================================================================
section("2. Pydantic model validation")

from pydantic import ValidationError

# Positive: minimal valid KnowledgeRef
ref = hc.KnowledgeRef(source="kf:graph", ontology_type="Policy", id="P-1")
check("KnowledgeRef minimal construct", ref.id == "P-1")

# Negative: KnowledgeRef rejects extra fields (extra=forbid)
try:
    hc.KnowledgeRef(source="x", ontology_type="y", id="z", bogus_field="q")
    check("KnowledgeRef rejects extra fields", False, "should have raised")
except ValidationError:
    check("KnowledgeRef rejects extra fields", True)

# KnowledgeFact construction
fact = hc.KnowledgeFact(
    ref=ref, payload={"k": "v"}, fetched_by="test_resolver"
)
check("KnowledgeFact default truth_mode is hybrid",
      fact.truth_mode == hc.TruthSourceMode.HYBRID)

# AgentAction round-trip
action = hc.AgentAction(
    action_id="ACT-1", action_type="test", actor_id="agent-1", payload={"a": 1}
)
check("AgentAction default domain", action.domain == "supply_chain")

# StageContext requires stage + bound_by
try:
    hc.StageContext(facts=[fact])  # missing required fields
    check("StageContext requires stage + bound_by", False, "should have raised")
except ValidationError:
    check("StageContext requires stage + bound_by", True)


# =============================================================================
# 3. Build a minimal harness (binders, resolvers, fixtures)
# =============================================================================
section("3. Build minimal harness")


class _StubAgentBinder:
    def bind(self, agent_id, scenario):
        return hc.StageContext(
            stage=hc.Stage.AGENT_INTAKE,
            facts=[hc.KnowledgeFact(
                ref=hc.KnowledgeRef(source="iam", ontology_type="ActorScope", id=agent_id),
                payload={"scopes": ["read", "propose"]},
                fetched_by="iam_stub",
            )],
            bound_by="StubAgentBinder/test",
        )


class _StubProposalBinder:
    def bind(self, action):
        return hc.StageContext(
            stage=hc.Stage.PROPOSAL,
            facts=[hc.KnowledgeFact(
                ref=hc.KnowledgeRef(source="erp", ontology_type="Material", id="M-1"),
                payload={"material_id": "M-1"},
                fetched_by="erp_stub",
            )],
            bound_by="StubProposalBinder/test",
        )


class _StubReviewBinder:
    def bind(self, action, prior):
        return hc.StageContext(
            stage=hc.Stage.REVIEW,
            facts=[hc.KnowledgeFact(
                ref=hc.KnowledgeRef(source="kf:graph", ontology_type="SOP", id="SOP-1"),
                payload={"title": "Test SOP"},
                fetched_by="kf_stub",
            )],
            bound_by="StubReviewBinder/test",
        )


def _build_action():
    return hc.AgentAction(
        action_id="ACT-T1",
        action_type="test_action",
        actor_id="agent-test",
        payload={"shipment_id": "S-1"},
    )


check("Harness binders constructable", True)


# =============================================================================
# 4. Sync transport — three decision kinds
# =============================================================================
section("4. Sync transport — approve, reject, request_more_info")


def _make_sync_service(decision_kind: str):
    def _reviewer(card):
        return {
            "decision": decision_kind,
            "reviewer_id": "test.reviewer",
            "rationale": f"test {decision_kind}",
        }
    surface = hc.TeamsAdaptiveCardSurface()
    transport = hc.SyncInProcessTransport(surface=surface, decision_callable=_reviewer)
    lineage = hc.InMemoryLineageRecorder()
    service = hc.HITLContextService(
        agent_binder=_StubAgentBinder(),
        proposal_binder=_StubProposalBinder(),
        review_binder=_StubReviewBinder(),
        transport=transport, lineage=lineage,
    )
    return service, lineage


for kind in ["approve", "reject", "request_more_info"]:
    service, lineage = _make_sync_service(kind)
    ctx = service.open_case(agent_id="agent-test", scenario={},
                            transport_mode=hc.TransportMode.SYNC)
    service.attach_proposal(ctx, _build_action())
    ticket = service.submit_for_review(ctx)
    decision = service.collect_decision(ctx, ticket.ticket_id)

    check(f"sync/{kind}: decision returned", decision is not None)
    check(f"sync/{kind}: decision kind matches",
          decision and decision.decision.value == kind)
    check(f"sync/{kind}: reviewer captured",
          decision and decision.reviewer_id == "test.reviewer")
    check(f"sync/{kind}: ticket id wired into decision",
          decision and decision.ticket_id == ticket.ticket_id)
    check(f"sync/{kind}: ctx.decision populated", ctx.decision is not None)
    check(f"sync/{kind}: 3 stages bound", len(ctx.stages) == 3)
    # Lineage check: 4 events (intake, proposal, review submit, decision)
    check(f"sync/{kind}: 4 lineage events", len(ctx.lineage) == 4,
          f"got {len(ctx.lineage)}")
    # Sequence ordering
    seqs = [e.sequence for e in ctx.lineage]
    check(f"sync/{kind}: lineage append-only sequenced",
          seqs == sorted(seqs) and seqs == list(range(len(seqs))))
    # Lineage stage on decision: EXECUTE for approve, REVIEW for request_more_info, ABORT for reject
    last_stage = ctx.lineage[-1].stage
    if kind == "approve":
        check(f"sync/{kind}: last lineage stage is EXECUTE",
              last_stage == hc.Stage.EXECUTE)
    elif kind == "request_more_info":
        check(f"sync/{kind}: last lineage stage is REVIEW (loops back)",
              last_stage == hc.Stage.REVIEW,
              f"got {last_stage}")
    else:
        check(f"sync/{kind}: last lineage stage is ABORT",
              last_stage == hc.Stage.ABORT,
              f"got {last_stage}")


# =============================================================================
# 5. Async transport — submit, poll-before, poll-after
# =============================================================================
section("5. Async transport — submit / poll lifecycle")


class _MemQueue(hc.OutboundQueue):
    def __init__(self): self.messages = []
    def put(self, message): self.messages.append(message)


class _MemDecisionStore(hc.DecisionStore):
    def __init__(self): self._d: dict[str, hc.ReviewDecision] = {}
    def get(self, tid): return self._d.get(tid)
    def put(self, decision): self._d[decision.ticket_id] = decision
    def cancel(self, tid, reason): self._d.pop(tid, None)


queue = _MemQueue()
store = _MemDecisionStore()
surface = hc.TeamsAdaptiveCardSurface()
async_transport = hc.AsyncQueueTransport(
    review_queue=queue, decision_store=store, surface=surface
)
lineage = hc.InMemoryLineageRecorder()
service = hc.HITLContextService(
    agent_binder=_StubAgentBinder(),
    proposal_binder=_StubProposalBinder(),
    review_binder=_StubReviewBinder(),
    transport=async_transport, lineage=lineage,
)

ctx = service.open_case(agent_id="agent-test", scenario={},
                        transport_mode=hc.TransportMode.ASYNC)
service.attach_proposal(ctx, _build_action())
ticket = service.submit_for_review(ctx)

check("async: submit returns ticket", ticket is not None)
check("async: ticket transport=ASYNC", ticket.transport == hc.TransportMode.ASYNC)
check("async: queue has 1 message", len(queue.messages) == 1)
check("async: queued message has rendered card",
      "rendered" in queue.messages[0])
check("async: queued message has serialized context",
      "context" in queue.messages[0])

# Poll-before-decide returns None (decision not yet posted)
early = service.collect_decision(ctx, ticket.ticket_id)
check("async: collect_decision returns None before reviewer responds",
      early is None)

# Reviewer posts decision (simulating Teams callback handler)
posted = hc.ReviewDecision(
    ticket_id=ticket.ticket_id,
    case_id=ctx.case_id,
    decision=hc.ReviewDecisionKind.APPROVE,
    reviewer_id="async.reviewer",
    rationale="async test",
)
store.put(posted)

after = service.collect_decision(ctx, ticket.ticket_id)
check("async: collect_decision returns decision after post", after is not None)
check("async: returned decision matches posted",
      after and after.decision == hc.ReviewDecisionKind.APPROVE)
check("async: ctx.decision now populated", ctx.decision is not None)


# =============================================================================
# 6. Serialization round-trip — the cross-mode replay claim
# =============================================================================
section("6. JSON serialization round-trip")

# Take the populated async ctx from §5 and round-trip it.
serialized = ctx.model_dump(mode="json")
as_json = json.dumps(serialized)
check("ctx serializes to JSON", isinstance(as_json, str) and len(as_json) > 0)

reloaded = hc.KnowledgeContext.model_validate(json.loads(as_json))
check("ctx round-trips via JSON", reloaded.case_id == ctx.case_id)
check("round-tripped: same number of stages",
      len(reloaded.stages) == len(ctx.stages))
check("round-tripped: same lineage event count",
      len(reloaded.lineage) == len(ctx.lineage))
check("round-tripped: same number of facts",
      len(reloaded.all_facts()) == len(ctx.all_facts()))
check("round-tripped: decision preserved",
      reloaded.decision and
      reloaded.decision.decision == ctx.decision.decision)


# =============================================================================
# 7. Surface — Adaptive Card structure
# =============================================================================
section("7. Reviewer surface (Teams Adaptive Card)")

card = surface.render(ctx)
check("card type is AdaptiveCard", card.get("type") == "AdaptiveCard")
check("card version is 1.5", card.get("version") == "1.5")
check("card has body", isinstance(card.get("body"), list) and len(card["body"]) > 0)
check("card has 3 actions (approve/reject/more_info)",
      len(card.get("actions", [])) == 3)
action_titles = {a.get("title") for a in card.get("actions", [])}
check("actions include Approve, Reject, Need more info",
      action_titles == {"Approve", "Reject", "Need more info"})

# parse_decision round-trip
parsed = surface.parse_decision({
    "decision": "approve", "ticket_id": "t-1", "case_id": "c-1",
    "reviewer_id": "r-1", "rationale": "looks good",
})
check("parse_decision: decision kind", parsed.decision == hc.ReviewDecisionKind.APPROVE)
check("parse_decision: reviewer captured", parsed.reviewer_id == "r-1")


# =============================================================================
# 8. Lineage — append-only, knowledge_refs preserved
# =============================================================================
section("8. Lineage integrity")

last_event = ctx.lineage[-1]
check("last lineage event has sequence", isinstance(last_event.sequence, int))
check("first event sequence is 0", ctx.lineage[0].sequence == 0)
check("lineage events strictly increasing",
      all(ctx.lineage[i].sequence < ctx.lineage[i+1].sequence
          for i in range(len(ctx.lineage)-1)))
# Each bind event should record knowledge_refs
bind_events = [e for e in ctx.lineage if e.action == "bound"]
check("at least one bind event has knowledge_refs",
      any(len(e.knowledge_refs) > 0 for e in bind_events))


# =============================================================================
# 9. Edge: cancel via transport
# =============================================================================
section("9. Cancel via async transport")

cancel_ctx = service.open_case(agent_id="agent-x", scenario={},
                               transport_mode=hc.TransportMode.ASYNC)
service.attach_proposal(cancel_ctx, _build_action())
cancel_ticket = service.submit_for_review(cancel_ctx)
# Pre-populate then cancel
store.put(hc.ReviewDecision(
    ticket_id=cancel_ticket.ticket_id, case_id=cancel_ctx.case_id,
    decision=hc.ReviewDecisionKind.APPROVE, reviewer_id="x", rationale="x",
))
async_transport.cancel(cancel_ticket.ticket_id, "test cancel")
post_cancel = async_transport.poll(cancel_ticket.ticket_id)
check("cancel removes pending decision", post_cancel is None)


# =============================================================================
# Summary
# =============================================================================
print(f"\n{'='*60}")
print(f"Total: {PASSED + FAILED}   Passed: {PASSED}   Failed: {FAILED}")
if FAILURES:
    print("\nFailures:")
    for f in FAILURES:
        print(f)
    sys.exit(1)
print("All tests passed.")
sys.exit(0)
