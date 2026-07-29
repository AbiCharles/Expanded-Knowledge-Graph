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

    def public_dict(self) -> dict:
        """Serialise for the API / frontend (incl. the actual path taken)."""
        return {
            "pipeline_id": self.pipeline_id,
            "prompt": self.prompt,
            "status": self.status,
            "current_step": self.current_step,
            "terminal_decision": self.terminal_decision,
            "error": self.error,
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
