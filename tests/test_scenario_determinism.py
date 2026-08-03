"""Unit tests for scenario answer-mode inference (router Strategy-A eligibility)."""
from __future__ import annotations

from pathlib import Path

import yaml

from backend.scenario_determinism import answer_mode, is_deterministic, pulls_from_source

_SCENARIO_DIR = Path(__file__).resolve().parent.parent / "backend" / "scenarios"


def _sc(**kw) -> dict:
    base = {"id": "SC-X", "title": "X", "domain": "demo"}
    base.update(kw)
    return base


def test_self_contained_autonomous_is_deterministic():
    sc = _sc(autonomous=True, stages={"proposal": {"facts": [{"id": "1"}]}})
    assert answer_mode(sc) == "deterministic"
    assert is_deterministic(sc)
    assert not pulls_from_source(sc)


def test_autonomous_with_ontology_query_is_deterministic_source():
    sc = _sc(autonomous=True, stages={"proposal": {"ontology_queries": [{"ontology": "o", "class": "C"}]}})
    assert answer_mode(sc) == "deterministic_source"
    assert is_deterministic(sc)  # still Strategy-A: one fixed outcome
    assert pulls_from_source(sc)


def test_hitl_scenario_is_pipeline():
    sc = _sc(autonomous=False, stages={"review": {"ontology_queries": [{"ontology": "o", "class": "C"}]}})
    assert answer_mode(sc) == "pipeline"
    assert not is_deterministic(sc)


def test_autonomous_with_risk_bands_is_pipeline():
    # Conditional autonomy (can be demoted to HITL) is NOT deterministic.
    sc = _sc(autonomous=True, risk_bands={"high": {}}, stages={"proposal": {"facts": []}})
    assert answer_mode(sc) == "pipeline"
    assert not is_deterministic(sc)


def test_author_override_wins():
    sc = _sc(autonomous=False, answer_mode="deterministic")
    assert answer_mode(sc) == "deterministic"


def test_shipped_scenarios_classify_as_expected():
    auto14 = yaml.safe_load((_SCENARIO_DIR / "SC-PP-AUTO-014.yaml").read_text())
    assert is_deterministic(auto14), "self-contained autonomous scenario should be Strategy-A"

    tiern = yaml.safe_load((_SCENARIO_DIR / "SC-PP-TIER-N-025.yaml").read_text())
    assert not is_deterministic(tiern), "multi-hop HITL scenario should not be Strategy-A"
