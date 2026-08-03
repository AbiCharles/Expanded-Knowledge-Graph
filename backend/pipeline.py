"""Multi-scenario pipeline record (Phase 2).

A pipeline links an ordered chain of cases — one per scenario step — that a
single question spawned ("compose then branch"). `run_pipeline` (in
pipeline_orchestrator.py) executes the steps in order: each step runs as a
real HITL case, and the next step only launches when the prior step's
decision lets the workflow proceed. The record also carries the probability
forecast so the UI can overlay the *actual* path taken onto the projected map.

In-memory only (mirrors the review queue / decision store): a restart drops
in-flight pipelines. The per-step `case_id`s are persisted on their cases.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .outcome_plan import OutcomePlan
from .probability import CONTINUE_KINDS

_HITL_DECISIONS = ("approve", "reject", "request_more_info")


def _best_path(path_edge_ids: list[list[str]], edge_by_id: dict) -> list[str]:
    """Pick the most-probable path (max product of edge probabilities)."""
    def prob(path: list[str]) -> float:
        p = 1.0
        for eid in path:
            e = edge_by_id.get(eid)
            if e is not None:
                p *= float(e.probability)
        return p

    return max(path_edge_ids, key=prob) if path_edge_ids else []


def _decisions_along(edge_ids: list[str], edge_by_id: dict, node_by_id: dict) -> list[dict]:
    """Every decision-node edge along the path (gate + HITL), in order."""
    out: list[dict] = []
    for eid in edge_ids:
        e = edge_by_id.get(eid)
        if e is None:
            continue
        src = node_by_id.get(e.source)
        if src is not None and src.kind == "decision" and src.scenario_id:
            out.append({"scenario_id": src.scenario_id, "decision": e.label, "step_index": src.step_index})
    return out


def viable_paths(forecast: OutcomePlan) -> list[dict]:
    """Actionable root->outcome paths the reviewer can approve, ranked.

    "Actionable" excludes the early dead-ends — a path whose only decision is a
    first-scenario reject / request-more-info (the workflow never proceeds).
    The most-probable survivor is tagged ``recommended``. Each entry lists the
    per-scenario HITL decisions the path prescribes (what execution applies).
    """
    node_by_id = {n.id: n for n in forecast.nodes}
    edge_by_id = {e.id: e for e in forecast.edges}
    # The first scenario in the pipeline (lowest step_index) — a reject/more-info
    # that terminates HERE is an early dead-end the workflow never got past.
    step_nodes = [n for n in forecast.nodes if n.kind == "scenario_step"]
    first_scenario_id = (
        min(step_nodes, key=lambda n: (n.step_index or 10**9)).scenario_id if step_nodes else None
    )
    paths: list[dict] = []
    for outcome in forecast.outcomes:
        if not outcome.path_edge_ids:
            continue
        # Exclude the early dead-ends: stopping at the first scenario without acting.
        if outcome.scenario_id == first_scenario_id and outcome.outcome_kind in (
            "reject", "request_more_info"
        ):
            continue
        best = _best_path(outcome.path_edge_ids, edge_by_id)
        decisions = _decisions_along(best, edge_by_id, node_by_id)
        if not decisions:
            continue
        # Only the HITL decisions are prescribed to execution (the autonomy
        # gate is deterministic and handled by run_case).
        hitl_steps = [d for d in decisions if d["decision"] in _HITL_DECISIONS]
        paths.append({
            "path_id": outcome.id,
            "label": outcome.label,
            "outcome_kind": outcome.outcome_kind,
            "probability": outcome.probability,
            "steps": hitl_steps,
            "recommended": False,
        })
    paths.sort(key=lambda p: p["probability"], reverse=True)
    if paths:
        paths[0]["recommended"] = True
    return paths


def prescribed_for_path(forecast: OutcomePlan, path_id: str) -> dict[str, str]:
    """scenario_id -> HITL decision for the chosen path. Raises KeyError."""
    for p in viable_paths(forecast):
        if p["path_id"] == path_id:
            return {d["scenario_id"]: d["decision"] for d in p["steps"]}
    raise KeyError(path_id)


@dataclass
class PipelineStepState:
    scenario_id: str
    title: str
    why: str = ""
    case_id: Optional[str] = None      # the case created for this step
    decision: Optional[str] = None     # approve|reject|request_more_info|auto_execute|...


@dataclass
class PipelineRecord:
    pipeline_id: str
    prompt: str
    user_id: Optional[int]
    steps: list[PipelineStepState]
    forecast: OutcomePlan
    status: str = "planned"  # planned | running | complete | error
    current_step: int = 0
    terminal_decision: Optional[str] = None
    error: Optional[str] = None
    # The pathway the reviewer approved for execution (an outcome/path id).
    chosen_path_id: Optional[str] = None

    def public_dict(self) -> dict:
        """Serialise for the API / frontend (incl. the actual path taken)."""
        return {
            "pipeline_id": self.pipeline_id,
            "prompt": self.prompt,
            "status": self.status,
            "current_step": self.current_step,
            "terminal_decision": self.terminal_decision,
            "error": self.error,
            "chosen_path_id": self.chosen_path_id,
            # Actionable pathways the reviewer can approve (recommended tagged).
            "viable_paths": viable_paths(self.forecast),
            "steps": [
                {
                    "scenario_id": s.scenario_id,
                    "title": s.title,
                    "why": s.why,
                    "case_id": s.case_id,
                    "decision": s.decision,
                }
                for s in self.steps
            ],
            # Only the steps that have actually resolved so far — this is what
            # the frontend paints onto the forecast graph as the taken path.
            "actual_path": [
                {"step": i, "scenario_id": s.scenario_id, "decision": s.decision}
                for i, s in enumerate(self.steps)
                if s.decision is not None
            ],
            "forecast": self.forecast.model_dump(),
        }
