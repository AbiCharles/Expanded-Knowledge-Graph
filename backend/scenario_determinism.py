"""Infer a scenario's answer *mode* from its declared fields.

The query router (`backend/agent_runtime.py` `route_query`) uses this to decide
whether a matched scenario is a Strategy-A candidate — a deterministic,
single-outcome pathway that answers straight from the scenario definition (zero
or single-source I/O) — versus a Strategy-B multi-hop / HITL scenario.

Determinism is *inferred*, not authored: no scenario ships a `deterministic` or
`difficulty` field. The signal is:
  - `autonomous: true`  → one fixed `auto_execute` outcome, no human branch
    (`backend/policy.py` / `orchestrator._finalise_autonomous`);
  - no `ontology_queries` in any stage → the answer needs no external source
    (`backend/binders.py` only pulls when `ontology_queries` is present);
  - no `risk_bands` → autonomy can't be demoted to HITL at run time
    (`backend/risk_band.py`).

An optional top-level `answer_mode:` in the YAML lets an author force a tier when
the inference is wrong.
"""
from __future__ import annotations

from typing import Any, Literal

AnswerMode = Literal["deterministic", "deterministic_source", "pipeline"]

_OVERRIDE_KEY = "answer_mode"
_VALID_OVERRIDES: frozenset[str] = frozenset({"deterministic", "deterministic_source", "pipeline"})


def _has_ontology_queries(scenario: dict[str, Any]) -> bool:
    """True if any stage binds at least one live ontology query (a source pull)."""
    stages = scenario.get("stages")
    if not isinstance(stages, dict):
        return False
    return any(
        isinstance(stage, dict) and stage.get("ontology_queries")
        for stage in stages.values()
    )


def answer_mode(scenario: dict[str, Any]) -> AnswerMode:
    """Classify how a scenario produces its answer.

    - ``"deterministic"``        — autonomous, no source pull, no risk gate; the
      answer is fully contained in the scenario file (e.g. ``SC-PP-AUTO-014``).
    - ``"deterministic_source"`` — autonomous, single fixed outcome, but binds
      one or more ontology queries (e.g. ``SC-ONTO-*``, autonomous ``SC-LN-*``).
    - ``"pipeline"``             — HITL and/or multi-hop; routed through review.
    """
    override = scenario.get(_OVERRIDE_KEY)
    if isinstance(override, str) and override in _VALID_OVERRIDES:
        return override  # type: ignore[return-value]  # author-forced tier

    autonomous = scenario.get("autonomous") is True
    if not autonomous or scenario.get("risk_bands"):
        return "pipeline"
    return "deterministic_source" if _has_ontology_queries(scenario) else "deterministic"


def is_deterministic(scenario: dict[str, Any]) -> bool:
    """True when a matched single scenario can definitively answer (Strategy A).

    Both self-contained and single-source autonomous scenarios qualify: each has
    one fixed outcome and no human/branch divergence.
    """
    return answer_mode(scenario) in ("deterministic", "deterministic_source")


def pulls_from_source(scenario: dict[str, Any]) -> bool:
    """Whether answering this scenario requires an external data pull."""
    return answer_mode(scenario) != "deterministic"
