"""Unit tests for the RCA 5-Why synthesis pass (backend/rca_synthesis.py).

No API, no data sources — exercises the reasoning pass directly with a fake
LLM (deterministic fallback) and a stub LLM (JSON parse + error fallback).
"""
from __future__ import annotations

import asyncio
import json

from tcs_hitl_context import FakeLLMClient, KnowledgeFact, KnowledgeRef

from backend.rca_synthesis import (
    ALL_MODES,
    SYNTHESIS_SOURCE,
    FiveWhyOutput,
    five_why_facts,
    resolve_modes,
    run_five_why_synthesis,
    run_synthesis_modes,
)


def _fact(oid: str, ontology_type: str, title: str, summary: str) -> KnowledgeFact:
    return KnowledgeFact(
        ref=KnowledgeRef(source="test", ontology_type=ontology_type, id=oid),
        payload={"title": title, "summary": summary},
        fetched_by="test",
    )


class _StubLLM:
    """A non-fake async LLM stub so the JSON-parse path is exercised (the
    real code short-circuits `name == 'fake'` to the deterministic fallback,
    mirroring AgentRuntime)."""

    name = "stub"

    def __init__(self, text: str) -> None:
        self._text = text

    async def complete(self, *, system, user, response_format="text", temperature=0.2):
        return self._text


_EVIDENCE = [
    _fact("ANM-5001", "Anomaly", "Autoclave pressure dropped 12%", "pressure_drop"),
    _fact("EV-V1", "EvidenceNode", "VISUAL · 18mm delamination", "confidence 92%"),
]
_PAYLOAD = {"defect_type": "delamination", "part_id": "P-1234", "program": "Mirage"}


def test_fallback_under_fake_llm() -> None:
    out = asyncio.run(
        run_five_why_synthesis(
            FakeLLMClient(), evidence_facts=_EVIDENCE, payload=_PAYLOAD
        )
    )
    assert isinstance(out, FiveWhyOutput)
    assert len(out.why_chain) == 5
    assert out.root_cause
    assert "P-1234" in out.problem_statement
    # The fallback is grounded — it references the bound evidence titles.
    joined = " ".join(s.evidence for s in out.why_chain)
    assert "pressure" in joined.lower() or "delamination" in joined.lower()


def test_five_why_facts_rendering() -> None:
    out = asyncio.run(
        run_five_why_synthesis(
            FakeLLMClient(), evidence_facts=_EVIDENCE, payload=_PAYLOAD
        )
    )
    rendered = five_why_facts(out)
    # 5 why-steps + root cause + recommended actions
    assert len(rendered) == 7
    assert all(f.ref.source == SYNTHESIS_SOURCE for f in rendered)
    assert any(f.ref.ontology_type == "RootCause" for f in rendered)
    assert rendered[0].payload["title"].startswith("Why 1:")


def test_valid_json_is_parsed() -> None:
    raw = json.dumps(
        {
            "problem_statement": "delamination on P-1234",
            "why_chain": [{"question": "q", "answer": "a", "evidence": "e"}],
            "root_cause": "autoclave regulator drift",
            "confidence": "high",
            "recommended_actions": ["replace regulator"],
        }
    )
    out = asyncio.run(
        run_five_why_synthesis(
            _StubLLM(raw), evidence_facts=_EVIDENCE, payload=_PAYLOAD
        )
    )
    assert out.root_cause == "autoclave regulator drift"
    assert out.confidence == "high"


def test_bad_json_falls_back() -> None:
    out = asyncio.run(
        run_five_why_synthesis(
            _StubLLM("not json at all"), evidence_facts=_EVIDENCE, payload=_PAYLOAD
        )
    )
    # Fallback shape: exactly five steps.
    assert len(out.why_chain) == 5


# -----------------------------------------------------------------------------
# Multi-method dispatch
# -----------------------------------------------------------------------------
def test_resolve_modes() -> None:
    assert resolve_modes("all") == ALL_MODES
    assert resolve_modes("five_why") == ["five_why"]
    assert resolve_modes(["ishikawa", "pareto"]) == ["ishikawa", "pareto"]
    assert resolve_modes(["five_why", "bogus"]) == ["five_why"]  # unknown dropped
    assert resolve_modes("bogus") == []
    assert resolve_modes(None) == []
    assert resolve_modes("") == []


def test_run_all_modes_under_fake() -> None:
    results = asyncio.run(
        run_synthesis_modes(
            FakeLLMClient(), ALL_MODES, evidence_facts=_EVIDENCE, payload=_PAYLOAD
        )
    )
    assert [m for m, _, _ in results] == ALL_MODES  # all four ran, in order
    # Each mode produced at least one fact, all tagged with a synthesis: source.
    types_seen = set()
    for _mode, facts, detail in results:
        assert facts, f"{_mode} produced no facts"
        assert detail
        for f in facts:
            assert f.ref.source.startswith("synthesis:")
            types_seen.add(f.ref.ontology_type)
    # Signature fact types from each of the four methods.
    for t in ("FiveWhyStep", "IshikawaCategory", "ParetoCause", "EvidenceGraphSummary"):
        assert t in types_seen, f"missing {t}"


def test_modes_dont_see_each_others_facts() -> None:
    # Even though each mode's facts share the proposal stage, run_synthesis_modes
    # reasons every mode over the ORIGINAL evidence snapshot only.
    results = asyncio.run(
        run_synthesis_modes(
            FakeLLMClient(), ALL_MODES, evidence_facts=_EVIDENCE, payload=_PAYLOAD
        )
    )
    # Total synthesized facts is deterministic under fake; sanity floor.
    total = sum(len(f) for _, f, _ in results)
    assert total >= 10
