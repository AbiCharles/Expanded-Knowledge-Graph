"""Unit tests for viable-path derivation + prescribed decisions."""
from __future__ import annotations

import pytest

from backend.pipeline import prescribed_for_path, viable_paths
from backend.scenario_composer import compose
from backend.scenario_loader import ScenarioRegistry

HITL = {
    "id": "SC-HITL",
    "title": "Human review scenario",
    "autonomous": False,
    "outcomes": {"approve": {"headline": "Approved"}, "reject": {"headline": "Rejected"},
                 "request_more_info": {"headline": "More info"}},
}
AUTO = {
    "id": "SC-AUTO",
    "title": "Autonomous release",
    "autonomous": True,
    "action_payload": {"po_value_usd": 14_000_000},
    "risk_bands": {"high": {"escalate_to": "review_ready",
                            "when": {"payload_field": "po_value_usd", "op": "gt", "threshold": 10_000_000}}},
    "outcomes": {"auto_execute": {"headline": "Auto"}, "review_ready": {"headline": "Escalated"},
                 "approve": {"headline": "Approved"}, "reject": {"headline": "Rejected"},
                 "request_more_info": {"headline": "More info"}},
}


def _forecast(scenarios, ids):
    reg = ScenarioRegistry({s["id"]: s for s in scenarios}, directory=None)
    return compose("q", ids, scenarios=reg)


def test_viable_paths_exclude_early_stops_and_tag_recommended():
    plan = _forecast([HITL, AUTO], ["SC-HITL", "SC-AUTO"])
    vps = viable_paths(plan)
    assert vps
    # No early dead-ends (a single first-scenario reject/rmi).
    for p in vps:
        assert not (len(p["steps"]) == 1 and p["steps"][0]["decision"] in ("reject", "request_more_info"))
    # Exactly one recommended, and it's the highest probability.
    assert sum(1 for p in vps if p["recommended"]) == 1
    assert vps[0]["recommended"]
    assert all(vps[0]["probability"] >= p["probability"] for p in vps)
    # Every actionable path here proceeds past step 1 (SC-AUTO decisions present).
    assert any(any(s["scenario_id"] == "SC-AUTO" for s in p["steps"]) for p in vps)


def test_prescribed_decisions_are_valid_kinds():
    plan = _forecast([HITL, AUTO], ["SC-HITL", "SC-AUTO"])
    rec = next(p for p in viable_paths(plan) if p["recommended"])
    prescribed = prescribed_for_path(plan, rec["path_id"])
    assert prescribed  # at least the first scenario's decision
    assert all(v in ("approve", "reject", "request_more_info") for v in prescribed.values())


def test_single_scenario_reject_path_is_not_viable():
    plan = _forecast([HITL], ["SC-HITL"])
    vps = viable_paths(plan)
    kinds = {p["outcome_kind"] for p in vps}
    assert "approve" in kinds
    assert "reject" not in kinds and "request_more_info" not in kinds


def test_prescribed_unknown_path_raises():
    plan = _forecast([HITL], ["SC-HITL"])
    with pytest.raises(KeyError):
        prescribed_for_path(plan, "does-not-exist")
