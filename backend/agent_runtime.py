"""Agent runtime — wraps the LLM with two structured calls.

  1. `interpret_prompt(text)`   → classify which scenario applies, paraphrase
                                  what the agent is going to do, draft a
                                  clarifying question.
  2. `draft_action(scenario, …)` → produce the AgentAction the framework
                                   needs at the proposal stage.

Both calls request JSON and validate against typed Pydantic models. If the LLM
is unavailable or the user picked LLM_PROVIDER=fake, we fall back to keyword
matching and the scenario's declared template (so the demo runs end-to-end
without credentials).
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field
from tcs_hitl_context import AgentAction, LLMClient

from .scenario_loader import ScenarioRegistry

log = logging.getLogger(__name__)


class ScenarioCandidate(BaseModel):
    """One ranked candidate from interpret_prompt."""
    scenario_id: str
    title: str
    confidence: float


class InterpretedRequest(BaseModel):
    """Result of `interpret_prompt`.

    `scenario_id` is the best match (may be None on full no-match). `candidates`
    is the ranked top-K including the best — exposed so the UI can offer
    "Did you mean…?" alternatives when confidence is low.
    """
    scenario_id: Optional[str] = Field(default=None)
    interpreted_as: str = ""
    clarifying_question: str = ""
    confidence: float = 0.0
    candidates: list[ScenarioCandidate] = Field(default_factory=list)


# Confidence below this threshold → UI should offer top-K alternatives.
SUGGEST_THRESHOLD = 0.7
TOP_K = 3


_CLASSIFY_SYSTEM = """You are the intake stage of a Human-in-the-Loop agent runtime for an enterprise supply-chain platform.
Given an operator's natural-language request, you must:
  1. Pick the top 3 scenarios from the catalog ranked by relevance, with a confidence score for each.
     Use null for scenario_id only when the request is genuinely outside every scenario in the catalog.
  2. Paraphrase the request as a single short clause beginning with a verb (no preamble).
  3. Draft a one-sentence clarifying question that confirms the best-matching action.
  4. Confidence scores are between 0.0 and 1.0; the top candidate's confidence reflects how
     well it matches versus the runners-up.

Respond with strict JSON only, matching this schema:
{
  "scenario_id": string|null,
  "interpreted_as": string,
  "clarifying_question": string,
  "confidence": number,
  "candidates": [
    {"scenario_id": string, "confidence": number},
    {"scenario_id": string, "confidence": number},
    {"scenario_id": string, "confidence": number}
  ]
}"""


class AgentRuntime:
    """Wraps the LLM with two structured calls used during case intake.

    1. ``interpret_prompt(text)`` — classify which scenario the operator's
       prompt matches and produce a paraphrase + clarifying question.
    2. ``draft_action(scenario)`` — instantiate the framework's
       ``AgentAction`` from the scenario's declared template payload.

    The runtime degrades gracefully when ``LLMClient.name == "fake"``:
    classification falls back to keyword matching against each scenario's
    ``match_keywords``. This lets the demo run end-to-end with no
    credentials.
    """

    def __init__(self, *, llm: LLMClient, scenarios: ScenarioRegistry):
        self.llm = llm
        self.scenarios = scenarios

    # -------------------------------------------------------------------------
    # Step 1 — classify + interpret
    # -------------------------------------------------------------------------
    async def interpret_prompt(self, text: str) -> InterpretedRequest:
        catalog_lines = []
        for sc in self.scenarios.all():
            catalog_lines.append(
                f"  - {sc['id']}: {sc['title']} ({sc['domain']}) — keywords: "
                + ", ".join(sc.get("match_keywords", []))
            )
        user_msg = (
            "Scenario catalog:\n"
            + "\n".join(catalog_lines)
            + f"\n\nOperator request: {text!r}\n\n"
            + "Return JSON only."
        )

        # Fake LLM short-circuits to keyword matching to keep the demo running.
        if self.llm.name == "fake":
            return self._fallback_interpret(text)

        try:
            raw = await self.llm.complete(
                system=_CLASSIFY_SYSTEM,
                user=user_msg,
                response_format="json",
                temperature=0.1,
            )
            parsed = json.loads(raw)
            return self._post_process_llm_result(parsed, fallback_text=text)
        except Exception:
            log.exception("LLM interpret_prompt failed; falling back to keyword match")
            return self._fallback_interpret(text)

    def _post_process_llm_result(
        self, parsed: dict[str, Any], *, fallback_text: str
    ) -> InterpretedRequest:
        """Validate the LLM's JSON and drop any hallucinated scenario ids."""
        # Filter candidates to ones that actually exist
        candidates: list[ScenarioCandidate] = []
        for c in parsed.get("candidates", []) or []:
            sid = c.get("scenario_id")
            if not sid:
                continue
            sc = self.scenarios.get(sid)
            if sc is None:
                continue
            candidates.append(
                ScenarioCandidate(
                    scenario_id=sid,
                    title=sc["title"],
                    confidence=float(c.get("confidence", 0.0)),
                )
            )
        candidates = sorted(candidates, key=lambda c: -c.confidence)[:TOP_K]
        if not candidates:
            log.warning("LLM produced no valid candidates; falling back")
            return self._fallback_interpret(fallback_text)

        # Top result drives clarifier + interpreted_as
        top = candidates[0]
        # If the LLM's stated scenario_id matches our top candidate, take its
        # interpreted_as / clarifying_question; otherwise sync to the top candidate.
        scenario_id = parsed.get("scenario_id") or top.scenario_id
        if scenario_id != top.scenario_id and self.scenarios.get(scenario_id) is None:
            scenario_id = top.scenario_id

        sc = self.scenarios.require(scenario_id)
        return InterpretedRequest(
            scenario_id=scenario_id,
            interpreted_as=parsed.get("interpreted_as") or sc.get("interpreted_as", ""),
            clarifying_question=parsed.get("clarifying_question") or sc.get("clarifying_question", ""),
            confidence=float(parsed.get("confidence", top.confidence)),
            candidates=candidates,
        )

    def _fallback_interpret(self, text: str) -> InterpretedRequest:
        """Keyword-match fallback. Returns top-K by keyword hit count."""
        lower = text.lower()
        scored: list[tuple[int, dict]] = []
        for sc in self.scenarios.all():
            score = sum(1 for kw in sc.get("match_keywords", []) if kw in lower)
            if score > 0:
                scored.append((score, sc))
        scored.sort(key=lambda t: -t[0])

        if not scored:
            # Truly novel — surface the 3 scenarios as a generic catalog so the
            # operator at least sees what's available.
            generic = self.scenarios.all()[:TOP_K]
            return InterpretedRequest(
                scenario_id=None,
                interpreted_as="",
                clarifying_question=(
                    "I'm not sure which scenario fits this request. "
                    "Pick one below or try a more specific prompt."
                ),
                confidence=0.0,
                candidates=[
                    ScenarioCandidate(scenario_id=sc["id"], title=sc["title"], confidence=0.0)
                    for sc in generic
                ],
            )

        candidates = [
            ScenarioCandidate(
                scenario_id=sc["id"],
                title=sc["title"],
                confidence=min(1.0, 0.5 + 0.1 * score),
            )
            for score, sc in scored[:TOP_K]
        ]
        top_score, top_sc = scored[0]
        return InterpretedRequest(
            scenario_id=top_sc["id"],
            interpreted_as=top_sc.get("interpreted_as", ""),
            clarifying_question=top_sc.get("clarifying_question", ""),
            confidence=candidates[0].confidence,
            candidates=candidates,
        )

    # -------------------------------------------------------------------------
    # Step 2 — draft the AgentAction. For the demo this just instantiates the
    # scenario's declared template; a real agent would fill it from the prompt.
    # -------------------------------------------------------------------------
    def draft_action(self, scenario: dict[str, Any]) -> AgentAction:
        """Build the framework ``AgentAction`` for this scenario.

        Pins ``__scenario_id__`` into the payload so binders downstream can
        look up the same scenario when they need to read its declared facts
        or queries. In a fuller agent this would also call the LLM to fill
        scenario-specific fields from the operator's prompt; for the demo
        the YAML's ``action_payload`` template is used as-is.
        """
        action_id = f"ACT-{uuid.uuid4().hex[:10].upper()}"
        payload = dict(scenario.get("action_payload", {}))
        # Pin the scenario id so the proposal/review binders can pick the right fixture.
        payload["__scenario_id__"] = scenario["id"]
        return AgentAction(
            action_id=action_id,
            action_type=scenario["action_type"],
            actor_id=scenario["actor_id"],
            domain=scenario.get("domain"),
            payload=payload,
        )
