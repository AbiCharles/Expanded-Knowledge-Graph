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
from typing import Any, Literal, Optional

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


class PipelineStep(BaseModel):
    """One scenario in a planned multi-scenario pipeline (in run order)."""
    scenario_id: str
    title: str
    why: str = ""


class PipelinePlan(BaseModel):
    """Result of `plan_pipeline` — an ordered pipeline of 1..N scenarios.

    `steps` is the compose order: the first is the entry point; each later
    step is reached only if the prior step's decision lets the workflow
    proceed. `len(steps) >= 2` means the question is genuinely multi-scenario.
    """
    steps: list[PipelineStep] = Field(default_factory=list)
    rationale: str = ""
    confidence: float = 0.0

    @property
    def multi(self) -> bool:
        return len(self.steps) >= 2


# Answer-strategy names by probability index [A, B, C].
_STRATEGIES: tuple[str, str, str] = ("deterministic", "pipeline", "rag")
# Expected-correctness weight per strategy (A > B > C); drives the meter.
_CORRECTNESS_WEIGHTS: tuple[float, float, float] = (1.0, 0.75, 0.45)


def _normalize3(vals: list[float]) -> list[float]:
    """Clamp negatives to 0 and scale to sum 1; uniform when degenerate."""
    clamped = [v if v > 0 else 0.0 for v in vals]
    total = sum(clamped)
    if total <= 0:
        return [1 / 3, 1 / 3, 1 / 3]
    return [v / total for v in clamped]


class RouteResult(BaseModel):
    """The query router's answer-strategy decision.

    ``p_a``/``p_b``/``p_c`` sum to 1 (deterministic single scenario /
    multi-scenario pipeline / RAG-generative). ``strategy`` is the argmax;
    ``confidence`` is the expected correctness of that answer (A weighted
    highest, C lowest).
    """
    p_a: float
    p_b: float
    p_c: float
    strategy: Literal["deterministic", "pipeline", "rag"]
    confidence: float
    rationale: str = ""
    basis: Literal["llm", "heuristic"] = "heuristic"


# Confidence below this threshold → UI should offer top-K alternatives.
SUGGEST_THRESHOLD = 0.7
TOP_K = 3
# Max scenarios the keyword-chain fallback will stitch together.
MAX_PIPELINE_STEPS = 4


_CLASSIFY_SYSTEM = """You are the intake stage of a Human-in-the-Loop agent runtime for an enterprise supply-chain platform.
Given an operator's natural-language request, you must:
  1. Pick the top 3 scenarios from the catalog ranked by relevance, with a confidence score for each.
     Use null for scenario_id only when the request is genuinely outside every scenario in the catalog.
  2. Paraphrase the request as a single short clause beginning with a verb (no preamble).
  3. Draft a one-sentence clarifying question that confirms the best-matching action.
     If the scenario title implies multiple bindings (e.g. "scorecard + recent shipments",
     "trace and milestones", "scorecard and shipments"), the clarifier MUST confirm that
     BOTH bindings will be returned together — never ask the operator to pick between
     them. End the clarifier with "Proceed?" so it reads as a yes/no confirmation.
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


_PLAN_SYSTEM = """You are the pipeline planner for a Human-in-the-Loop supply-chain agent runtime.
Given an operator's natural-language question and the scenario catalog, decide whether answering it requires a SEQUENCE of scenarios ("compose then branch") or a single scenario.

Rules:
  - Return an ORDERED pipeline. The first step is the entry point; each later step is one the workflow only reaches if the prior step's decision lets it proceed (e.g. the reviewer approves, then a follow-on action is triggered).
  - Return MULTIPLE steps ONLY when the question genuinely spans multiple dependent decisions (e.g. "if we approve a mitigation for the failing supplier, what happens to the follow-on bulk PO?"). If it's a single ask, return exactly one step.
  - Use only scenario_ids that exist in the catalog. Give a short `why` for each step.

Respond with strict JSON only:
{
  "steps": [ {"scenario_id": string, "why": string} ],
  "rationale": string,
  "confidence": number
}"""


_ROUTER_SYSTEM = """You are the answer-strategy router for an enterprise supply-chain assistant.
Given a user's question, decide HOW it is best answered, as a probability distribution over three strategies:
  - A (deterministic): ONE governed scenario with a single definitive outcome — often answerable from the scenario definition itself. Favour A when one scenario clearly and fully covers the question.
  - B (pipeline): one OR MORE governed scenarios answered over mapped ontologies, pulling from source systems, with human review and/or multiple possible outcomes. Favour B when a scenario fits but the answer is not a single deterministic value (it needs source data and/or review), or when the question spans several dependent scenarios.
  - C (rag): a retrieval/generative answer from the policy corpus or general knowledge. Favour C when NO scenario fits well (open policy / how-to / definitional questions).

You are told the best single-scenario match, whether that match is a deterministic scenario, and whether the planner found a multi-scenario pipeline. Weigh those signals.

Respond with strict JSON only (p_a + p_b + p_c should total ~1.0):
{ "p_a": number, "p_b": number, "p_c": number, "rationale": string }"""


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
    # Step 1b — plan a (possibly multi-scenario) pipeline from the prompt
    # -------------------------------------------------------------------------
    async def plan_pipeline(self, text: str) -> PipelinePlan:
        """Plan an ordered pipeline of scenarios for a natural-language question.

        With a real LLM this reasons over the catalog and returns a chain when
        the question spans dependent decisions. With the fake LLM (or on any
        failure) it falls back to keyword-chaining: scenarios whose
        `match_keywords` hit the prompt, ordered by hit count.
        """
        if self.llm.name == "fake":
            return self._keyword_chain(text)

        catalog_lines = [
            f"  - {sc['id']}: {sc['title']} ({sc.get('domain', '')}) — keywords: "
            + ", ".join(sc.get("match_keywords", []))
            for sc in self.scenarios.all()
        ]
        user_msg = (
            "Scenario catalog:\n" + "\n".join(catalog_lines)
            + f"\n\nOperator question: {text!r}\n\nReturn JSON only."
        )
        try:
            raw = await self.llm.complete(
                system=_PLAN_SYSTEM, user=user_msg,
                response_format="json", temperature=0.1,
            )
            parsed = json.loads(raw)
            steps: list[PipelineStep] = []
            seen: set[str] = set()
            for s in parsed.get("steps", []) or []:
                sid = s.get("scenario_id")
                sc = self.scenarios.get(sid) if sid else None
                if sc is None or sid in seen:
                    continue
                seen.add(sid)
                steps.append(PipelineStep(scenario_id=sid, title=sc["title"], why=s.get("why", "")))
                if len(steps) >= MAX_PIPELINE_STEPS:
                    break
            if not steps:
                return self._keyword_chain(text)
            return PipelinePlan(
                steps=steps,
                rationale=parsed.get("rationale", ""),
                confidence=float(parsed.get("confidence", 0.0)),
            )
        except Exception:
            log.exception("LLM plan_pipeline failed; keyword-chain fallback")
            return self._keyword_chain(text)

    def _keyword_chain(self, text: str) -> PipelinePlan:
        """Keyword-match fallback. 2+ matching scenarios → a chained pipeline."""
        lower = text.lower()
        scored: list[tuple[int, dict]] = []
        for sc in self.scenarios.all():
            score = sum(1 for kw in sc.get("match_keywords", []) if kw and kw in lower)
            if score > 0:
                scored.append((score, sc))
        scored.sort(key=lambda t: -t[0])
        if not scored:
            return PipelinePlan(steps=[], rationale="No scenario keywords matched the question.")
        if len(scored) >= 2:
            chosen = scored[:MAX_PIPELINE_STEPS]
            rationale = "Keyword-chain fallback — multiple scenarios matched the question."
        else:
            chosen = scored[:1]
            rationale = "Keyword fallback — a single scenario matched."
        steps = [
            PipelineStep(scenario_id=sc["id"], title=sc["title"], why=f"{score} keyword match(es)")
            for score, sc in chosen
        ]
        return PipelinePlan(
            steps=steps, rationale=rationale,
            confidence=min(1.0, 0.5 + 0.1 * chosen[0][0]),
        )

    # -------------------------------------------------------------------------
    # Step 1c — route the query across answer strategies (A / B / C)
    # -------------------------------------------------------------------------
    async def route_query(
        self,
        text: str,
        interpreted: InterpretedRequest,
        plan: Optional[PipelinePlan],
        *,
        top_is_deterministic: bool,
    ) -> RouteResult:
        """Score the question across the three answer strategies and pick one.

        Hybrid: an LLM router when credentials are present, else a heuristic that
        fuses the signals the two classifiers already produced (no extra call).
        """
        if self.llm.name == "fake":
            return self._route_heuristic(interpreted, plan, top_is_deterministic)

        multi = bool(plan and plan.multi)
        top = interpreted.candidates[0] if interpreted.candidates else None
        user_msg = (
            f"Question: {text!r}\n"
            f"Best scenario match: {top.scenario_id if top else 'none'} "
            f"(confidence {interpreted.confidence:.2f}, deterministic={top_is_deterministic})\n"
            f"Planner found a multi-scenario pipeline: {multi}\n\n"
            "Return JSON only."
        )
        try:
            raw = await self.llm.complete(
                system=_ROUTER_SYSTEM, user=user_msg,
                response_format="json", temperature=0.1,
            )
            parsed = json.loads(raw)
            probs = _normalize3([
                float(parsed.get("p_a", 0.0)),
                float(parsed.get("p_b", 0.0)),
                float(parsed.get("p_c", 0.0)),
            ])
            return self._build_route(probs, str(parsed.get("rationale", "")), basis="llm")
        except Exception:
            log.exception("LLM route_query failed; heuristic fallback")
            return self._route_heuristic(interpreted, plan, top_is_deterministic)

    def _route_heuristic(
        self,
        interpreted: InterpretedRequest,
        plan: Optional[PipelinePlan],
        top_is_deterministic: bool,
    ) -> RouteResult:
        """Fuse existing confidence signals into the 3-way distribution.

        A wins for a confident deterministic single-scenario match; B for any
        other confident scenario match (single-but-source/HITL, or a multi-step
        plan — i.e. the ontology pipeline); C is the residual mass when no
        scenario fits the question well.
        """
        c1 = float(interpreted.confidence or 0.0)
        plan_conf = float(plan.confidence) if plan else 0.0
        multi = bool(plan and plan.multi)
        deterministic_single = top_is_deterministic and not multi
        fit = max(c1, plan_conf if multi else 0.0)  # how well any scenario fits
        a = c1 * (1.0 if deterministic_single else 0.15)
        b = (plan_conf if multi else c1) * (0.15 if deterministic_single else 1.0)
        c = max(0.0, 1.0 - fit)
        probs = _normalize3([a, b, c])
        return self._build_route(probs, self._heuristic_rationale(probs), basis="heuristic")

    def _build_route(self, probs: list[float], rationale: str, *, basis: str) -> RouteResult:
        # Keep full precision so the three probabilities sum to exactly 1 (the
        # frontend formats them for display); only the scalar meter is rounded.
        idx = max(range(3), key=lambda i: probs[i])
        confidence = sum(p * w for p, w in zip(probs, _CORRECTNESS_WEIGHTS))
        return RouteResult(
            p_a=probs[0], p_b=probs[1], p_c=probs[2],
            strategy=_STRATEGIES[idx],
            confidence=round(confidence, 4),
            rationale=rationale, basis=basis,
        )

    @staticmethod
    def _heuristic_rationale(probs: list[float]) -> str:
        idx = max(range(3), key=lambda i: probs[i])
        return (
            "A single deterministic scenario cleanly covers this question.",
            "The question spans multiple scenarios that must be stitched together.",
            "No scenario fits well; answering generatively from the policy corpus.",
        )[idx]

    # -------------------------------------------------------------------------
    # Step 2 — draft the AgentAction. For the demo this just instantiates the
    # scenario's declared template; a real agent would fill it from the prompt.
    # -------------------------------------------------------------------------
    def draft_action(
        self,
        scenario: dict[str, Any],
        *,
        baseline: bool = False,
    ) -> AgentAction:
        """Build the framework ``AgentAction`` for this scenario.

        Pins ``__scenario_id__`` into the payload so binders downstream can
        look up the same scenario when they need to read its declared facts
        or queries. When ``baseline`` is True, also pins ``__baseline__``
        into the payload — the review-stage binder reads this flag and
        skips its ontology queries so the case ends up with an empty
        review stage (W5 / Beat 2: "what a supervisor without the governed
        knowledge layer would have surfaced").
        """
        action_id = f"ACT-{uuid.uuid4().hex[:10].upper()}"
        payload = dict(scenario.get("action_payload", {}))
        payload["__scenario_id__"] = scenario["id"]
        if baseline:
            payload["__baseline__"] = True
        return AgentAction(
            action_id=action_id,
            action_type=scenario["action_type"],
            actor_id=scenario["actor_id"],
            domain=scenario.get("domain"),
            payload=payload,
        )
