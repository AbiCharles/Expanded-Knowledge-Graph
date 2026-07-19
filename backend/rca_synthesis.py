"""RCA synthesis — the fabric-native port of RCA_agent's analysis agents.

The Knowledge Fabric's binders *retrieve* knowledge (evidence facts bound from
data sources). Root-cause analysis additionally needs an *inference* pass:
reasoning over that evidence. That is the one capability the fabric had no
equivalent for, so it lives here — ported from RCA_agent's analysis agents
(their prompts + `schemas/models.py` output shapes), rewired onto the fabric's
async `LLMClient`.

Four modes, mirroring RCA_agent's deep-analysis agents:
  - five_why       — sequential why-chain to a root cause
  - ishikawa       — 6-category (fishbone) cause classification
  - pareto         — ranked probable causes with % contribution (80/20)
  - evidence_graph — a synthesized causal graph summary + root cause

The orchestrator runs the modes a scenario's `stages.proposal.synthesis`
declares (`all` = every registered mode) and appends the results as facts to
the proposal envelope. Every mode degrades gracefully: with `LLM_PROVIDER=fake`
(or on any LLM error) it returns a deterministic, evidence-grounded fallback,
so the demo runs end-to-end without credentials.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field
from tcs_hitl_context import KnowledgeFact, KnowledgeRef, LLMClient

log = logging.getLogger(__name__)

SYNTHESIS_PREFIX = "synthesis:"
SYNTHESIS_SOURCE = "synthesis:five_why"  # kept for back-compat


# =============================================================================
# Shared helpers
# =============================================================================
def _evidence_digest(facts: list[KnowledgeFact]) -> str:
    lines: list[str] = []
    for f in facts:
        # Skip anything a synthesis mode produced (this or a prior pass).
        if f.ref.source.startswith(SYNTHESIS_PREFIX):
            continue
        title = f.payload.get("title") or ""
        summary = f.payload.get("summary") or ""
        lines.append(f"- [{f.ref.ontology_type}] {title} — {summary}".rstrip(" —"))
    return "\n".join(lines) or "(no structured evidence was bound)"


def _evidence_titles(facts: list[KnowledgeFact]) -> list[str]:
    return [
        f.payload.get("title") or f.payload.get("summary") or f.ref.id
        for f in facts
        if not f.ref.source.startswith(SYNTHESIS_PREFIX)
    ]


def _problem_statement(payload: dict[str, Any]) -> str:
    defect = payload.get("defect_type") or "defect"
    part = payload.get("part_id") or "the part"
    program = payload.get("program")
    base = f"{defect} on {part}"
    return f"{base} (program {program})" if program else base


def _fact(source: str, ontology_type: str, fid: str, title: str, summary: str) -> KnowledgeFact:
    return KnowledgeFact(
        ref=KnowledgeRef(source=source, ontology_type=ontology_type, id=fid),
        payload={"title": title, "summary": summary},
        fetched_by=source,
    )


async def _complete_json(llm: LLMClient, system: str, user: str) -> str:
    return await llm.complete(
        system=system, user=user, response_format="json", temperature=0.2
    )


# =============================================================================
# 1) Five-Why  (RCA_agent: FiveWhyOutput / WhyStep)
# =============================================================================
class WhyStep(BaseModel):
    question: str
    answer: str
    evidence: str = ""


class FiveWhyOutput(BaseModel):
    problem_statement: str
    why_chain: list[WhyStep] = Field(default_factory=list)
    root_cause: str
    confidence: str = "medium"
    recommended_actions: list[str] = Field(default_factory=list)


_FIVE_WHY_SYSTEM = """You are an expert industrial process-safety, quality-assurance, \
and forensic failure-analysis engineer performing a structured 5-Why root-cause \
analysis on a manufacturing defect.

Produce EXACTLY five sequential why-steps. Each answer must be grounded in the \
supplied evidence — cite the specific anomaly, observation, or evidence node in \
the `evidence` field. Do not invent evidence.

Respond with STRICT JSON only:
{"problem_statement": string,
 "why_chain": [{"question": string, "answer": string, "evidence": string}],
 "root_cause": string, "confidence": "low"|"medium"|"high",
 "recommended_actions": [string]}"""


async def run_five_why_synthesis(
    llm: LLMClient, *, evidence_facts: list[KnowledgeFact], payload: dict[str, Any]
) -> FiveWhyOutput:
    problem = _problem_statement(payload)
    user = (
        f"Problem statement: {problem}\n\nBound evidence:\n"
        f"{_evidence_digest(evidence_facts)}\n\nReturn the 5-Why analysis as strict JSON."
    )
    if getattr(llm, "name", "") != "fake":
        try:
            return FiveWhyOutput.model_validate_json(
                await _complete_json(llm, _FIVE_WHY_SYSTEM, user)
            )
        except Exception:  # noqa: BLE001
            log.exception("five-why synthesis failed; using fallback")
    return _five_why_fallback(problem, evidence_facts, payload)


def _five_why_fallback(
    problem: str, evidence_facts: list[KnowledgeFact], payload: dict[str, Any]
) -> FiveWhyOutput:
    titles = _evidence_titles(evidence_facts)
    e = (titles + ["the observed defect"] * 3)[:3]
    defect = payload.get("defect_type") or "defect"
    chain = [
        WhyStep(question=f"Why did the {defect} occur?",
                answer="A localized process excursion during manufacture left the "
                "affected region out of spec.", evidence=e[0]),
        WhyStep(question="Why was the region out of spec?",
                answer="The governing process parameter deviated from its qualified "
                "window during the operation.", evidence=e[1]),
        WhyStep(question="Why did the parameter deviate?",
                answer="An equipment/consumable condition upstream shifted the "
                "achievable setpoint.", evidence=e[2]),
        WhyStep(question="Why did that condition go undetected?",
                answer="No in-line gate caught the drift before the part was committed.",
                evidence="absence of a pre-operation verification step"),
        WhyStep(question="Why was there no gate?",
                answer="The control plan relied on post-hoc inspection rather than a "
                "preventive check.", evidence="control-plan review"),
    ]
    return FiveWhyOutput(
        problem_statement=problem, why_chain=chain,
        root_cause=f"Uncontrolled drift in the governing process parameter for the "
        f"{defect}, with no preventive in-line gate to catch it.",
        confidence="medium",
        recommended_actions=[
            "Add an in-line preventive check on the drifting parameter with an alarm.",
            "Recalibrate/replace the implicated equipment and add it to PM.",
            "Move the control plan from post-hoc inspection to in-process SPC.",
        ],
    )


def five_why_facts(output: FiveWhyOutput) -> list[KnowledgeFact]:
    src = "synthesis:five_why"
    facts: list[KnowledgeFact] = []
    for i, step in enumerate(output.why_chain, start=1):
        summary = step.answer + (f"  ·  evidence: {step.evidence}" if step.evidence else "")
        facts.append(_fact(src, "FiveWhyStep", f"why-{i}", f"Why {i}: {step.question}", summary))
    facts.append(_fact(src, "RootCause", "root-cause",
                       f"5-Why root cause ({output.confidence} confidence)", output.root_cause))
    if output.recommended_actions:
        facts.append(_fact(src, "RecommendedActions", "recommended-actions",
                           "Recommended corrective/preventive actions",
                           " · ".join(output.recommended_actions)))
    return facts


# =============================================================================
# 2) Ishikawa / fishbone  (RCA_agent: IshikawaOutput — 6 categories)
# =============================================================================
class IshikawaOutput(BaseModel):
    methods: list[str] = Field(default_factory=list)
    machines: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    measurement: list[str] = Field(default_factory=list)
    environment: list[str] = Field(default_factory=list)
    primary_root_cause: str = ""
    confidence: str = "medium"


_ISHIKAWA_SYSTEM = """You are a quality engineer building an Ishikawa (fishbone) \
diagram for a manufacturing defect. Classify the candidate causes across the six \
standard categories — Methods, Machines, People, Materials, Measurement, \
Environment — grounding each in the supplied evidence. Leave a category empty if \
nothing supports it. Then name the single most probable primary root cause.

Respond with STRICT JSON only:
{"methods": [string], "machines": [string], "people": [string],
 "materials": [string], "measurement": [string], "environment": [string],
 "primary_root_cause": string, "confidence": "low"|"medium"|"high"}"""


async def run_ishikawa_synthesis(
    llm: LLMClient, *, evidence_facts: list[KnowledgeFact], payload: dict[str, Any]
) -> IshikawaOutput:
    user = (
        f"Problem: {_problem_statement(payload)}\n\nBound evidence:\n"
        f"{_evidence_digest(evidence_facts)}\n\nReturn the Ishikawa classification as strict JSON."
    )
    if getattr(llm, "name", "") != "fake":
        try:
            return IshikawaOutput.model_validate_json(
                await _complete_json(llm, _ISHIKAWA_SYSTEM, user)
            )
        except Exception:  # noqa: BLE001
            log.exception("ishikawa synthesis failed; using fallback")
    return _ishikawa_fallback(evidence_facts, payload)


def _ishikawa_fallback(
    evidence_facts: list[KnowledgeFact], payload: dict[str, Any]
) -> IshikawaOutput:
    # Grounded-but-generic categorization keyed off common manufacturing themes.
    blob = " ".join(_evidence_titles(evidence_facts)).lower()

    def has(*words: str) -> bool:
        return any(w in blob for w in words)

    return IshikawaOutput(
        machines=[c for c in [
            "Autoclave pressure regulator drift" if has("pressure", "autoclave", "regulator") else "",
            "Equipment out of calibration" if has("calibrat", "regulator") else "",
        ] if c] or ["Process equipment condition"],
        methods=[c for c in [
            "Cure/dwell profile deviation" if has("dwell", "cure", "profile") else "",
            "No in-line preventive gate in the control plan",
        ] if c],
        materials=[c for c in [
            "Consumable/material out of spec" if has("resin", "viscosity", "prepreg", "bag") else "",
        ] if c],
        measurement=[c for c in [
            "Bag-integrity / leak check gap" if has("bag", "leak", "vacuum") else "",
        ] if c],
        environment=[],
        people=[],
        primary_root_cause="Uncontrolled equipment drift with no preventive gate "
        "(Machines × Methods).",
        confidence="medium",
    )


_ISHIKAWA_CATEGORIES = [
    ("machines", "Machines"), ("methods", "Methods"), ("materials", "Materials"),
    ("measurement", "Measurement"), ("people", "People"), ("environment", "Environment"),
]


def ishikawa_facts(output: IshikawaOutput) -> list[KnowledgeFact]:
    src = "synthesis:ishikawa"
    facts: list[KnowledgeFact] = []
    for attr, label in _ISHIKAWA_CATEGORIES:
        causes = getattr(output, attr) or []
        if causes:
            facts.append(_fact(src, "IshikawaCategory", f"ishikawa-{attr}",
                               f"Ishikawa · {label}", " · ".join(causes)))
    if output.primary_root_cause:
        facts.append(_fact(src, "RootCause", "ishikawa-primary",
                           f"Ishikawa primary cause ({output.confidence} confidence)",
                           output.primary_root_cause))
    return facts


# =============================================================================
# 3) Pareto  (RCA_agent: ParetoOutput — ranked causes with % contribution)
# =============================================================================
class ParetoOutput(BaseModel):
    pareto_items: list[str] = Field(default_factory=list)
    pareto_percent: list[float] = Field(default_factory=list)


_PARETO_SYSTEM = """You are a reliability engineer applying Pareto (80/20) analysis \
to a manufacturing defect. From the supplied evidence, list 3-6 probable causes \
ranked most-to-least likely, with an estimated percentage contribution for each. \
The percentages should sum to about 100.

Respond with STRICT JSON only:
{"pareto_items": [string], "pareto_percent": [number]}   // same length, ranked desc"""


async def run_pareto_synthesis(
    llm: LLMClient, *, evidence_facts: list[KnowledgeFact], payload: dict[str, Any]
) -> ParetoOutput:
    user = (
        f"Problem: {_problem_statement(payload)}\n\nBound evidence:\n"
        f"{_evidence_digest(evidence_facts)}\n\nReturn the Pareto ranking as strict JSON."
    )
    if getattr(llm, "name", "") != "fake":
        try:
            return ParetoOutput.model_validate_json(
                await _complete_json(llm, _PARETO_SYSTEM, user)
            )
        except Exception:  # noqa: BLE001
            log.exception("pareto synthesis failed; using fallback")
    return _pareto_fallback(evidence_facts)


def _pareto_fallback(evidence_facts: list[KnowledgeFact]) -> ParetoOutput:
    blob = " ".join(_evidence_titles(evidence_facts)).lower()
    ranked: list[tuple[str, float]] = []
    if "pressure" in blob or "regulator" in blob or "autoclave" in blob:
        ranked.append(("Autoclave pressure regulator drift", 55))
    if "bag" in blob or "vacuum" in blob or "leak" in blob:
        ranked.append(("Vacuum-bag leak during layup", 22))
    if "dwell" in blob or "cure" in blob:
        ranked.append(("Cure dwell-time deviation", 13))
    if "resin" in blob or "viscosity" in blob or "prepreg" in blob:
        ranked.append(("Material/resin out of spec", 10))
    if not ranked:
        ranked = [("Primary process excursion", 60), ("Secondary contributing factor", 25),
                  ("Material variation", 15)]
    return ParetoOutput(
        pareto_items=[r[0] for r in ranked], pareto_percent=[r[1] for r in ranked]
    )


def pareto_facts(output: ParetoOutput) -> list[KnowledgeFact]:
    src = "synthesis:pareto"
    pairs = list(zip(output.pareto_items, output.pareto_percent))
    pairs.sort(key=lambda p: -p[1])
    facts: list[KnowledgeFact] = []
    for i, (item, pct) in enumerate(pairs, start=1):
        facts.append(_fact(src, "ParetoCause", f"pareto-{i}",
                           f"Pareto #{i}: {item}", f"~{pct:g}% of estimated contribution"))
    if pairs:
        cum = 0.0
        vital = []
        for item, pct in pairs:
            cum += pct
            vital.append(item)
            if cum >= 80:
                break
        facts.append(_fact(src, "ParetoSummary", "pareto-vital-few",
                           "Pareto · vital few (≈80%)", " · ".join(vital)))
    return facts


# =============================================================================
# 4) Evidence-graph  (RCA_agent: EvidenceGraphOutput — synthesized causal graph)
# =============================================================================
class EGNode(BaseModel):
    node_id: str
    node_type: str = "inference"  # visual | log | inference | root_cause
    description: str = ""
    confidence_score: float = 50


class EGEdge(BaseModel):
    from_node: str
    to_node: str
    relationship_type: str = "supports"
    strength: float = 50


class EvidenceGraphOutput(BaseModel):
    nodes: list[EGNode] = Field(default_factory=list)
    edges: list[EGEdge] = Field(default_factory=list)
    primary_root_cause: str = ""
    overall_confidence: float = 50
    evidence_summary: str = ""


_EVIDENCE_GRAPH_SYSTEM = """You are a forensic analyst assembling a causal evidence \
graph for a manufacturing defect. From the supplied evidence, build a small \
directed graph of evidence nodes (types: visual, log, inference, root_cause) and \
the causal edges between them, then state the primary root cause and an overall \
confidence (0-100) with a one-paragraph summary.

Respond with STRICT JSON only:
{"nodes": [{"node_id": string, "node_type": string, "description": string, "confidence_score": number}],
 "edges": [{"from_node": string, "to_node": string, "relationship_type": string, "strength": number}],
 "primary_root_cause": string, "overall_confidence": number, "evidence_summary": string}"""


async def run_evidence_graph_synthesis(
    llm: LLMClient, *, evidence_facts: list[KnowledgeFact], payload: dict[str, Any]
) -> EvidenceGraphOutput:
    user = (
        f"Problem: {_problem_statement(payload)}\n\nBound evidence:\n"
        f"{_evidence_digest(evidence_facts)}\n\nReturn the evidence graph as strict JSON."
    )
    if getattr(llm, "name", "") != "fake":
        try:
            return EvidenceGraphOutput.model_validate_json(
                await _complete_json(llm, _EVIDENCE_GRAPH_SYSTEM, user)
            )
        except Exception:  # noqa: BLE001
            log.exception("evidence-graph synthesis failed; using fallback")
    return _evidence_graph_fallback(evidence_facts, payload)


def _evidence_graph_fallback(
    evidence_facts: list[KnowledgeFact], payload: dict[str, Any]
) -> EvidenceGraphOutput:
    titles = _evidence_titles(evidence_facts)
    nodes = [EGNode(node_id=f"n{i}", node_type="log" if i else "visual",
                    description=t, confidence_score=80 - i * 5)
             for i, t in enumerate(titles[:4])]
    root = EGNode(node_id="root", node_type="root_cause",
                  description=f"Root cause of the {payload.get('defect_type', 'defect')}",
                  confidence_score=78)
    nodes.append(root)
    edges = [EGEdge(from_node=n.node_id, to_node="root", relationship_type="supports",
                    strength=70) for n in nodes[:-1]]
    return EvidenceGraphOutput(
        nodes=nodes, edges=edges,
        primary_root_cause="Uncontrolled equipment drift converging on the defect, "
        "supported by the visual and log evidence.",
        overall_confidence=78,
        evidence_summary=f"{len(nodes)} evidence nodes converge via {len(edges)} "
        "causal links on a single root cause; the visual finding and the process "
        "logs are mutually corroborating.",
    )


def evidence_graph_facts(output: EvidenceGraphOutput) -> list[KnowledgeFact]:
    src = "synthesis:evidence_graph"
    facts: list[KnowledgeFact] = []
    if output.evidence_summary or output.nodes:
        facts.append(_fact(
            src, "EvidenceGraphSummary", "evidence-graph-summary",
            f"Evidence graph · {len(output.nodes)} nodes / {len(output.edges)} edges "
            f"({output.overall_confidence:g}% confidence)",
            output.evidence_summary or "Synthesized causal evidence graph."))
    if output.primary_root_cause:
        facts.append(_fact(src, "RootCause", "evidence-graph-root",
                           "Evidence-graph root cause", output.primary_root_cause))
    return facts


# =============================================================================
# Dispatch — run one or more modes over the bound evidence
# =============================================================================
async def _run_five_why(llm, ev, pl):
    out = await run_five_why_synthesis(llm, evidence_facts=ev, payload=pl)
    return five_why_facts(out), f"root cause: {out.root_cause} ({out.confidence} confidence)"


async def _run_ishikawa(llm, ev, pl):
    out = await run_ishikawa_synthesis(llm, evidence_facts=ev, payload=pl)
    cats = sum(1 for a, _ in _ISHIKAWA_CATEGORIES if getattr(out, a))
    return ishikawa_facts(out), f"{cats} cause categories · primary: {out.primary_root_cause}"


async def _run_pareto(llm, ev, pl):
    out = await run_pareto_synthesis(llm, evidence_facts=ev, payload=pl)
    top_cause = out.pareto_items[0] if out.pareto_items else "—"
    return pareto_facts(out), f"{len(out.pareto_items)} ranked causes · top: {top_cause}"


async def _run_evidence_graph(llm, ev, pl):
    out = await run_evidence_graph_synthesis(llm, evidence_facts=ev, payload=pl)
    return evidence_graph_facts(out), (
        f"{len(out.nodes)} nodes / {len(out.edges)} edges · {out.overall_confidence:g}% confidence"
    )


# mode name → coroutine returning (facts, lineage_detail)
MODES: dict[str, Callable[[LLMClient, list[KnowledgeFact], dict[str, Any]],
                          Awaitable[tuple[list[KnowledgeFact], str]]]] = {
    "five_why": _run_five_why,
    "ishikawa": _run_ishikawa,
    "pareto": _run_pareto,
    "evidence_graph": _run_evidence_graph,
}
ALL_MODES = ["five_why", "ishikawa", "pareto", "evidence_graph"]


def resolve_modes(synthesis: Any) -> list[str]:
    """Normalize a scenario's `stages.proposal.synthesis` value to a mode list.

    Accepts: "all" (every registered mode), a single mode string, or a list of
    mode strings. Unknown modes are dropped. Empty/None → no synthesis.
    """
    if not synthesis:
        return []
    if synthesis == "all":
        return list(ALL_MODES)
    if isinstance(synthesis, str):
        modes = [synthesis]
    elif isinstance(synthesis, list):
        modes = [str(m) for m in synthesis]
    else:
        return []
    return [m for m in modes if m in MODES]


async def run_synthesis_modes(
    llm: LLMClient, modes: list[str], *,
    evidence_facts: list[KnowledgeFact], payload: dict[str, Any],
) -> list[tuple[str, list[KnowledgeFact], str]]:
    """Run each mode over the SAME (original) evidence snapshot. Returns one
    (mode, facts, lineage_detail) tuple per mode. A mode that raises is skipped."""
    snapshot = list(evidence_facts)  # so later modes don't see earlier synthesis facts
    valid = [m for m in modes if m in MODES]
    # Run all methods concurrently — they're independent (each reads the same
    # snapshot). Turns N sequential LLM round-trips into one.
    settled = await asyncio.gather(
        *(MODES[m](llm, snapshot, payload) for m in valid), return_exceptions=True
    )
    results: list[tuple[str, list[KnowledgeFact], str]] = []
    for mode, r in zip(valid, settled):
        if isinstance(r, Exception):
            log.warning("synthesis mode %s failed; skipping (%s)", mode, r)
            continue
        facts, detail = r
        results.append((mode, facts, detail))
    return results
