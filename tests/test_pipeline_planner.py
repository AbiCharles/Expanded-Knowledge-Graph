"""Unit tests for AgentRuntime.plan_pipeline keyword-chain fallback."""
from __future__ import annotations

from backend.agent_runtime import AgentRuntime
from backend.scenario_loader import ScenarioRegistry
from tcs_hitl_context import FakeLLMClient

A = {"id": "SC-A", "title": "Alpha", "domain": "d", "match_keywords": ["alpha", "northwind"]}
B = {"id": "SC-B", "title": "Beta", "domain": "d", "match_keywords": ["beta", "auto-release"]}


def _runtime(*scenarios: dict) -> AgentRuntime:
    reg = ScenarioRegistry({s["id"]: s for s in scenarios}, directory=None)
    return AgentRuntime(llm=FakeLLMClient(), scenarios=reg)


async def test_two_scenarios_chain_into_multi():
    # "beta"+"auto-release" -> B scores 2; "alpha" -> A scores 1. Both match.
    plan = await _runtime(A, B).plan_pipeline("run alpha then auto-release the beta")
    assert plan.multi
    ids = [s.scenario_id for s in plan.steps]
    assert set(ids) == {"SC-A", "SC-B"}
    assert ids[0] == "SC-B"  # higher keyword score leads the pipeline


async def test_single_match_is_not_multi():
    plan = await _runtime(A, B).plan_pipeline("just alpha and northwind here")
    assert not plan.multi
    assert [s.scenario_id for s in plan.steps] == ["SC-A"]


async def test_no_match_is_empty():
    plan = await _runtime(A, B).plan_pipeline("totally unrelated gibberish")
    assert plan.steps == []
    assert not plan.multi


async def test_chain_is_capped():
    scenarios = [
        {"id": f"SC-{i}", "title": f"S{i}", "domain": "d", "match_keywords": ["kw"]}
        for i in range(8)
    ]
    plan = await _runtime(*scenarios).plan_pipeline("kw kw kw")
    assert plan.multi
    assert len(plan.steps) <= 4  # MAX_PIPELINE_STEPS
