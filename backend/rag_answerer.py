"""Strategy C — RAG / generative answerer.

Retrieve-then-generate over the policy corpus: pull the top-k most relevant
chunks from the registered ``policy_corpus`` vector source, then synthesise a
grounded natural-language answer with inline citations via the LLM. This is the
router's least-deterministic path — it runs only when a question fits no
scenario well.

Degrades safely:
  - no vector source / no embeddings → answer ungrounded from the LLM (``grounded=False``);
  - fake LLM (no credentials)        → a canned notice pointing at the top match.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from tcs_hitl_context import KnowledgeQuery

log = logging.getLogger(__name__)

# Default vector source id + retrieval depth (see backend/data/sources.yaml).
_POLICY_SOURCE_ID = "policy_corpus"
_TOP_K = 5

_RAG_SYSTEM = """You are the generative fallback for an enterprise supply-chain assistant.
Answer the user's question using ONLY the numbered policy excerpts provided.
- Ground every claim in the excerpts and cite them inline as [1], [2], ...
- If the excerpts do not contain the answer, say so plainly — never invent policy.
- Be concise (2-5 sentences)."""

_UNGROUNDED_SYSTEM = """You are the generative fallback for an enterprise supply-chain assistant.
No policy documents were retrievable for this question. Answer from general
knowledge, and state clearly that the answer is NOT grounded in the company's
policy corpus. Be concise."""


class RagCitation(BaseModel):
    """One retrieved chunk cited by the answer."""

    n: int  # inline marker [n]
    source: str  # e.g. "vector:policy_corpus"
    id: str  # "<file>#chunk-<k>"
    title: str
    snippet: str
    score: float  # cosine similarity [0,1]


class RagAnswer(BaseModel):
    """A Strategy-C generative answer (also the API response shape)."""

    answer: str
    citations: list[RagCitation] = Field(default_factory=list)
    grounded: bool  # True when synthesised from retrieved excerpts
    confidence: float  # 0..1 (mean citation score, else a low prior)


def _retrieve(state, prompt: str, top_k: int) -> list:
    """Top-k policy chunks for the prompt, or [] when retrieval is unavailable."""
    resolver = state.data_sources.get(_POLICY_SOURCE_ID)
    if resolver is None:
        return []
    query = KnowledgeQuery(
        ontology_type="PolicyExcerpt",
        filters={"query": prompt, "top_k": top_k},
        max_results=top_k,
        requested_by="rag_answerer",
        purpose=prompt,
    )
    try:
        return resolver.resolve(query)
    except Exception:  # noqa: BLE001 — retrieval must never break the request
        log.exception("RAG retrieval failed for %r", prompt[:80])
        return []


async def answer_via_rag(state, prompt: str, *, top_k: int = _TOP_K) -> RagAnswer:
    """Retrieve policy excerpts and synthesise a grounded answer (Strategy C)."""
    facts = _retrieve(state, prompt, top_k)
    citations = [
        RagCitation(
            n=i + 1,
            source=fact.ref.source,
            id=fact.ref.id,
            title=str(fact.payload.get("title", fact.ref.id)),
            snippet=str(fact.payload.get("summary", "")),
            score=float(fact.confidence or 0.0),
        )
        for i, fact in enumerate(facts)
    ]

    llm = state.llm
    # No LLM credentials → can't synthesise prose; surface the top match instead.
    if getattr(llm, "name", "fake") == "fake":
        note = "Generative answering is unavailable without an LLM. " + (
            f"Most relevant policy: {citations[0].title}." if citations else "No policy match found."
        )
        return RagAnswer(answer=note, citations=citations, grounded=bool(citations), confidence=0.0)

    if citations:
        excerpts = "\n\n".join(f"[{c.n}] {c.title}\n{c.snippet}" for c in citations)
        user = f"Question: {prompt}\n\nPolicy excerpts:\n{excerpts}"
        system, grounded = _RAG_SYSTEM, True
        confidence = round(sum(c.score for c in citations) / len(citations), 4)
    else:
        user = f"Question: {prompt}"
        system, grounded, confidence = _UNGROUNDED_SYSTEM, False, 0.2

    try:
        answer = await llm.complete(system=system, user=user, response_format="text", temperature=0.2)
    except Exception:  # noqa: BLE001 — synthesis failure degrades to the retrieved match
        log.exception("RAG synthesis failed")
        answer = "Could not generate an answer right now." + (
            f" See policy: {citations[0].title}." if citations else ""
        )
        confidence = 0.0

    return RagAnswer(answer=answer.strip(), citations=citations, grounded=grounded, confidence=confidence)
