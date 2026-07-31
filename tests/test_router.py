"""Unit tests for the deterministic answer-strategy router.

Routing is count-based over the two classifiers' outputs:
  - a confident single-scenario match → A ("single");
  - a multi-scenario plan             → B ("pipeline");
  - no confident scenario match       → C ("rag", strictly last resort).
"""
from __future__ import annotations

from backend.agent_runtime import (
    AgentRuntime,
    InterpretedRequest,
    PipelinePlan,
    PipelineStep,
    ScenarioCandidate,
    _normalize3,
)
from backend.scenario_loader import ScenarioRegistry
from tcs_hitl_context import FakeLLMClient


def _runtime() -> AgentRuntime:
    return AgentRuntime(llm=FakeLLMClient(), scenarios=ScenarioRegistry({}, directory=None))


def _interp(conf: float, sid: str | None = "SC-A") -> InterpretedRequest:
    cands = [ScenarioCandidate(scenario_id=sid, title="A", confidence=conf)] if sid else []
    return InterpretedRequest(scenario_id=sid, confidence=conf, candidates=cands)


def _plan(multi: bool, conf: float = 0.8) -> PipelinePlan:
    steps = [PipelineStep(scenario_id="SC-A", title="A")]
    if multi:
        steps.append(PipelineStep(scenario_id="SC-B", title="B"))
    return PipelinePlan(steps=steps, confidence=conf)


def _route(interp, plan, det=False):
    return _runtime().route_query(interp, plan, top_is_deterministic=det)


def _sums_to_one(r) -> bool:
    return abs(r.p_a + r.p_b + r.p_c - 1.0) < 1e-6


def test_confident_single_routes_A():
    r = _route(_interp(0.95), _plan(False, 0.3), det=True)
    assert r.strategy == "single"
    assert r.p_a > r.p_b and r.p_a > r.p_c
    assert _sums_to_one(r)


def test_confident_single_hitl_also_routes_A_not_C():
    # A single confident match that is NOT deterministic is still A (one
    # scenario) — and must never fall through to RAG.
    r = _route(_interp(0.9), _plan(False, 0.0), det=False)
    assert r.strategy == "single"
    assert r.p_c < r.p_a


def test_multi_routes_B():
    r = _route(_interp(0.6), _plan(True, 0.85))
    assert r.strategy == "pipeline"
    assert r.p_b > r.p_a and r.p_b > r.p_c


def test_weak_single_match_routes_C():
    # A below-threshold single match (spurious keyword hit) → RAG.
    r = _route(_interp(0.5, "SC-X"), _plan(False, 0.0))
    assert r.strategy == "rag"
    assert r.p_c > r.p_a


def test_no_match_routes_C():
    r = _route(_interp(0.0, None), _plan(False, 0.0))
    assert r.strategy == "rag"
    assert r.p_c > r.p_b


def test_probs_normalized_and_confidence_ordering():
    r_a = _route(_interp(0.95), _plan(False, 0.2), det=True)
    r_c = _route(_interp(0.05, None), _plan(False, 0.0))
    for r in (r_a, r_c):
        assert _sums_to_one(r)
        assert 0.0 <= r.confidence <= 1.0
        assert r.basis == "rule"
    # A (a single governed scenario) reads as more correct than a C answer.
    assert r_a.confidence > r_c.confidence


def test_autonomous_single_is_full_confidence():
    # A single deterministic (autonomous) scenario reads as 100% correct.
    r = _route(_interp(0.9), _plan(False, 0.1), det=True)
    assert r.strategy == "single"
    assert r.confidence == 1.0


def test_hitl_single_is_below_full_confidence():
    # A single but review-based scenario is high, not full.
    r = _route(_interp(0.9), _plan(False, 0.0), det=False)
    assert r.strategy == "single"
    assert r.confidence < 1.0


def test_normalize3_handles_degenerate_input():
    assert _normalize3([0, 0, 0]) == [1 / 3, 1 / 3, 1 / 3]
    assert abs(sum(_normalize3([2, 0, -5])) - 1.0) < 1e-9
