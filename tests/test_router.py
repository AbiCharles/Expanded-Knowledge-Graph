"""Unit tests for the answer-strategy router (heuristic path via the fake LLM)."""
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


def _sums_to_one(r) -> bool:
    return abs(r.p_a + r.p_b + r.p_c - 1.0) < 1e-6


async def test_deterministic_single_routes_A():
    r = await _runtime().route_query("q", _interp(0.95), _plan(False, 0.3), top_is_deterministic=True)
    assert r.strategy == "deterministic"
    assert r.p_a > r.p_b and r.p_a > r.p_c
    assert _sums_to_one(r)


async def test_confident_single_hitl_routes_B_not_C():
    # A single, confident, NON-deterministic scenario match is the ontology
    # pipeline (B) — it must NOT fall through to RAG.
    r = await _runtime().route_query("q", _interp(0.8), _plan(False, 0.0), top_is_deterministic=False)
    assert r.strategy == "pipeline"
    assert r.p_b > r.p_c


async def test_multi_routes_B():
    r = await _runtime().route_query("q", _interp(0.6), _plan(True, 0.85), top_is_deterministic=False)
    assert r.strategy == "pipeline"
    assert r.p_b > r.p_a


async def test_weak_match_routes_C():
    r = await _runtime().route_query("q", _interp(0.1, sid=None), _plan(False, 0.0), top_is_deterministic=False)
    assert r.strategy == "rag"
    assert r.p_c >= r.p_a and r.p_c >= r.p_b


async def test_probs_normalized_and_confidence_ordering():
    r_det = await _runtime().route_query("q", _interp(0.95), _plan(False, 0.2), top_is_deterministic=True)
    r_rag = await _runtime().route_query("q", _interp(0.05, sid=None), _plan(False, 0.0), top_is_deterministic=False)
    for r in (r_det, r_rag):
        assert _sums_to_one(r)
        assert 0.0 <= r.confidence <= 1.0
        assert r.basis == "heuristic"
    # A-weighted answer should read as more correct than a C-weighted one.
    assert r_det.confidence > r_rag.confidence


def test_normalize3_handles_degenerate_input():
    assert _normalize3([0, 0, 0]) == [1 / 3, 1 / 3, 1 / 3]
    assert abs(sum(_normalize3([2, 0, -5])) - 1.0) < 1e-9
