"""Unit tests for the hybrid probability model (backend/probability.py)."""
from __future__ import annotations

import math

from backend.probability import (
    apply_reliability,
    author_overrides_for,
    branch_distribution,
)

HITL = ("approve", "reject", "request_more_info")


def _sums_to_one(dist: dict[str, float]) -> bool:
    return math.isclose(sum(dist.values()), 1.0, abs_tol=1e-9)


def test_defaults_used_when_no_author_or_history():
    dist, basis = branch_distribution(
        HITL, defaults={"approve": 0.6, "reject": 0.25, "request_more_info": 0.15}
    )
    assert _sums_to_one(dist)
    assert dist["approve"] > dist["reject"] > dist["request_more_info"]
    assert set(basis.values()) == {"default"}


def test_uniform_when_nothing_supplied():
    dist, basis = branch_distribution(HITL)
    assert _sums_to_one(dist)
    assert all(math.isclose(v, 1 / 3, abs_tol=1e-9) for v in dist.values())
    assert set(basis.values()) == {"default"}


def test_history_dominates_and_is_smoothed():
    # 8 approve, 2 reject, 0 request_more_info -> approve-leaning but the
    # never-seen branch still gets a Laplace sliver (not zero).
    dist, basis = branch_distribution(
        HITL, history_counts={"approve": 8, "reject": 2}
    )
    assert _sums_to_one(dist)
    assert dist["approve"] > dist["reject"] > 0
    assert dist["request_more_info"] > 0  # smoothed, never exactly zero
    assert set(basis.values()) == {"history"}


def test_author_override_wins_and_leftover_follows_history():
    # Author pins approve=0.5; the remaining 0.5 is split over reject/rmi by
    # their history share (reject seen 3x, rmi 1x).
    dist, basis = branch_distribution(
        HITL,
        history_counts={"reject": 3, "request_more_info": 1},
        author_overrides={"approve": 0.5},
    )
    assert _sums_to_one(dist)
    assert math.isclose(dist["approve"], 0.5, abs_tol=1e-9)
    assert dist["reject"] > dist["request_more_info"]
    assert basis["approve"] == "author"
    assert basis["reject"] == "history"


def test_reliability_shifts_approve_reject():
    base = {"approve": 0.5, "reject": 0.3, "request_more_info": 0.2}
    high = apply_reliability(base, 1.0)
    low = apply_reliability(base, 0.0)
    assert _sums_to_one(high) and _sums_to_one(low)
    assert high["approve"] > base["approve"] > low["approve"]
    assert low["reject"] > base["reject"] > high["reject"]
    # No-op when reliability is None.
    assert apply_reliability(base, None) == base


def test_author_overrides_extraction_from_scenario():
    scenario = {
        "id": "SC-X",
        "branch_probabilities": {"approve": 0.4},
        "outcomes": {
            "approve": {"headline": "ok", "probability": 0.7},  # per-outcome wins
            "reject": {"headline": "no"},
        },
    }
    overrides = author_overrides_for(scenario)
    assert overrides["approve"] == 0.7  # per-outcome beats branch_probabilities
    assert "reject" not in overrides  # no numeric probability -> not pinned
