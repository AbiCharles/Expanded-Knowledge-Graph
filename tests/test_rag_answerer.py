"""Unit tests for the Strategy-C RAG answerer + its degrade paths."""
from __future__ import annotations

from backend.rag_answerer import RagAnswer, answer_via_rag
from tcs_hitl_context import FakeLLMClient, KnowledgeFact, KnowledgeRef


class _StubResolver:
    def __init__(self, facts):
        self._facts = facts

    def resolve(self, query):
        return self._facts


class _StubDataSources:
    def __init__(self, resolver):
        self._resolver = resolver

    def get(self, source_id):
        return self._resolver


class _StubState:
    def __init__(self, resolver, llm):
        self.data_sources = _StubDataSources(resolver)
        self.llm = llm


class _SynthLLM:
    name = "openai"

    async def complete(self, *, system, user, response_format="text", temperature=0.2):
        return "Two people must approve high-risk overrides. [1]"


def _fact(title: str, score: float) -> KnowledgeFact:
    return KnowledgeFact(
        ref=KnowledgeRef(source="vector:policy_corpus", ontology_type="PolicyExcerpt", id=f"{title}#chunk-0"),
        payload={"title": title, "summary": "excerpt text"},
        fetched_by="policy_corpus",
        confidence=score,
    )


async def test_no_resolver_degrades_ungrounded():
    ans = await answer_via_rag(_StubState(None, FakeLLMClient()), "what is the two-person rule?")
    assert isinstance(ans, RagAnswer)
    assert ans.grounded is False
    assert ans.citations == []


async def test_fake_llm_returns_notice_with_citations():
    state = _StubState(_StubResolver([_fact("TWO-PERSON-RULE", 0.9)]), FakeLLMClient())
    ans = await answer_via_rag(state, "two person rule?")
    assert ans.grounded is True
    assert [c.title for c in ans.citations] == ["TWO-PERSON-RULE"]
    assert "unavailable" in ans.answer.lower()  # canned, no synthesis without an LLM
    assert ans.confidence == 0.0


async def test_real_llm_synthesizes_grounded_answer():
    state = _StubState(_StubResolver([_fact("TWO-PERSON-RULE", 0.8)]), _SynthLLM())
    ans = await answer_via_rag(state, "two person rule?")
    assert ans.grounded is True
    assert "[1]" in ans.answer
    assert ans.confidence > 0.0
