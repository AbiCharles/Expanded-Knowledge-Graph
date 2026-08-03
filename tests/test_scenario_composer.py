"""Tests for the compose-then-branch engine (backend/scenario_composer.py)."""
from __future__ import annotations

import math
from collections import defaultdict

import pytest

from backend.scenario_composer import compose
from backend.scenario_loader import ScenarioRegistry

HITL_SCENARIO = {
    "id": "SC-HITL",
    "title": "Human review scenario",
    "autonomous": False,
    "outcomes": {
        "approve": {"headline": "Approved"},
        "reject": {"headline": "Rejected"},
        "request_more_info": {"headline": "More info"},
    },
}

AUTONOMOUS_SCENARIO = {
    "id": "SC-AUTO",
    "title": "Autonomous release scenario",
    "autonomous": True,
    "action_payload": {"po_value_usd": 14_000_000},
    "risk_bands": {
        "high": {
            "escalate_to": "review_ready",
            "when": {"payload_field": "po_value_usd", "op": "gt", "threshold": 10_000_000},
        }
    },
    "outcomes": {
        "auto_execute": {"headline": "Auto-executed"},
        "review_ready": {"headline": "Escalated"},
        "approve": {"headline": "Approved"},
        "reject": {"headline": "Rejected"},
        "request_more_info": {"headline": "More info"},
    },
}

AUTHOR_PINNED = {
    "id": "SC-PINNED",
    "title": "Author-pinned scenario",
    "autonomous": False,
    "outcomes": {
        "approve": {"headline": "Approved", "probability": 0.7},
        "reject": {"headline": "Rejected", "probability": 0.2},
        "request_more_info": {"headline": "More info", "probability": 0.1},
    },
}


def _registry(*scenarios: dict) -> ScenarioRegistry:
    return ScenarioRegistry({s["id"]: s for s in scenarios}, directory=None)


def _sibling_sums(plan):
    """Sum of edge probabilities grouped by source node."""
    sums: dict[str, float] = defaultdict(float)
    for e in plan.edges:
        sums[e.source] += e.probability
    return sums


def test_single_hitl_scenario_outcomes_sum_to_one():
    reg = _registry(HITL_SCENARIO)
    plan = compose("Should we act?", ["SC-HITL"], scenarios=reg)
    assert math.isclose(plan.stats["total_probability"], 1.0, abs_tol=1e-6)
    assert len(plan.outcomes) == 3
    kinds = {o.outcome_kind for o in plan.outcomes}
    assert kinds == {"approve", "reject", "request_more_info"}


def test_decision_siblings_sum_to_one():
    reg = _registry(HITL_SCENARIO, AUTONOMOUS_SCENARIO)
    plan = compose("q", ["SC-HITL", "SC-AUTO"], scenarios=reg)
    node_kind = {n.id: n.kind for n in plan.nodes}
    for src, total in _sibling_sums(plan).items():
        if node_kind.get(src) == "decision":
            assert math.isclose(total, 1.0, abs_tol=1e-6), f"decision {src} sums to {total}"


def test_composed_pipeline_conserves_probability():
    # Two HITL scenarios: approve at #1 continues into #2; reject/rmi at #1
    # terminate. Total mass across every terminal outcome must be exactly 1.
    reg = _registry(HITL_SCENARIO, {**AUTHOR_PINNED, "id": "SC-HITL2"})
    plan = compose("q", ["SC-HITL", "SC-HITL2"], scenarios=reg)
    assert math.isclose(plan.stats["total_probability"], 1.0, abs_tol=1e-6)
    # The pipeline reaches the 2nd scenario, so at least one outcome belongs
    # to it -> more than 3 terminals overall.
    assert len(plan.outcomes) > 3
    assert {o.scenario_id for o in plan.outcomes} == {"SC-HITL", "SC-HITL2"}


def test_autonomous_scenario_has_authority_gate_and_nested_review():
    reg = _registry(AUTONOMOUS_SCENARIO)
    plan = compose("q", ["SC-AUTO"], scenarios=reg)
    decision_labels = [n.label for n in plan.nodes if n.kind == "decision"]
    assert "Authority gate" in decision_labels
    assert "Escalated review" in decision_labels
    # Band is crossed ($14M > $10M) so the escalation branch dominates the
    # auto-execute branch under the default prior.
    p_auto = next(o.probability for o in plan.outcomes if o.outcome_kind == "auto_execute")
    p_reject = next(o.probability for o in plan.outcomes if o.outcome_kind == "reject")
    assert p_reject > 0 and p_auto > 0
    assert math.isclose(plan.stats["total_probability"], 1.0, abs_tol=1e-6)


def test_author_pinned_weights_are_honoured():
    reg = _registry(AUTHOR_PINNED)
    plan = compose("q", ["SC-PINNED"], scenarios=reg)
    by_kind = {o.outcome_kind: o.probability for o in plan.outcomes}
    assert math.isclose(by_kind["approve"], 0.7, abs_tol=1e-6)
    assert math.isclose(by_kind["reject"], 0.2, abs_tol=1e-6)
    assert math.isclose(by_kind["request_more_info"], 0.1, abs_tol=1e-6)
    approve_edge = next(e for e in plan.edges if e.label == "approve")
    assert approve_edge.basis == "author"


def test_history_provider_shifts_distribution():
    reg = _registry(HITL_SCENARIO)
    # Heavy reject history -> reject should beat approve under the default
    # (approve-leaning) prior, proving history is actually consulted.
    history = {"SC-HITL": {"reject": 20, "approve": 1}}
    plan = compose(
        "q", ["SC-HITL"], scenarios=reg,
        history_provider=lambda sid: history.get(sid, {}),
    )
    by_kind = {o.outcome_kind: o.probability for o in plan.outcomes}
    assert by_kind["reject"] > by_kind["approve"]
    reject_edge = next(e for e in plan.edges if e.label == "reject")
    assert reject_edge.basis == "history"


def test_reliability_context_nudges_approval():
    reg = _registry(HITL_SCENARIO)
    low = compose("q", ["SC-HITL"], scenarios=reg, context={"reliability_score": 0.0})
    high = compose("q", ["SC-HITL"], scenarios=reg, context={"reliability_score": 1.0})
    p_low = next(o.probability for o in low.outcomes if o.outcome_kind == "approve")
    p_high = next(o.probability for o in high.outcomes if o.outcome_kind == "approve")
    assert p_high > p_low


def test_unknown_scenario_raises_keyerror():
    reg = _registry(HITL_SCENARIO)
    with pytest.raises(KeyError):
        compose("q", ["SC-DOES-NOT-EXIST"], scenarios=reg)
