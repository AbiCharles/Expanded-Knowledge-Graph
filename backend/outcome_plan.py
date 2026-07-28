"""Typed models for a *composed* answer — the Outcome DAG.

A single complex question is often answered by stitching several scenarios
together ("compose then branch"): the scenarios chain into a pipeline, and
wherever a scenario reaches a decision (a HITL reviewer choice, or an
autonomous authority-gate) the flow fans out into distinct possible
outcomes. This module holds the shape of that graph; `scenario_composer`
builds it and `probability` weights it.

The graph is a DAG:
  - one ``question`` root,
  - a ``scenario_step`` + ``decision`` node per stitched scenario,
  - ``outcome`` terminals.

Every edge carries a ``probability``; sibling edges out of a ``decision``
node sum to 1. A path's probability is the product of its edge
probabilities; an outcome's probability is the sum over the paths that
reach it. The models are Pydantic (v2) so `api/graph.py` can return an
``OutcomePlan`` straight as a ``response_model`` and the frontend can map
it onto Cytoscape elements.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# Node kinds understood by the frontend renderer.
NODE_KINDS = ("question", "scenario_step", "decision", "outcome")

# Basis tags explaining WHERE an edge's probability came from — surfaced in
# the UI so a reviewer can see whether a weight is author-set, data-derived,
# agent-adjusted, or a structural (deterministic) hop.
EDGE_BASES = ("author", "history", "default", "agent", "structural")


class OutcomeNode(BaseModel):
    id: str
    label: str
    kind: str = Field(..., description="One of NODE_KINDS")
    scenario_id: Optional[str] = None
    step_index: Optional[int] = None
    # For ``outcome`` nodes: the decision kind that produced it
    # (approve|reject|request_more_info|auto_execute|review_ready).
    outcome_kind: Optional[str] = None
    # Aggregate probability of reaching this node — filled in for ``outcome``
    # terminals by `compute_outcomes`. None for interior nodes.
    probability: Optional[float] = None
    # Reused by the frontend stylesheet for colour (mirrors GraphNode.accent
    # in api/graph.py): "anchor" | "risk" | "risk_path" | "alt" | "".
    accent: str = ""


class OutcomeEdge(BaseModel):
    id: str
    source: str
    target: str
    # Decision kind (e.g. "approve") for branch edges, or a structural label
    # ("proposal", "start") for deterministic hops.
    label: str = ""
    probability: float = 1.0
    basis: str = Field("structural", description="One of EDGE_BASES")
    # Short human-readable explanation of the weight (e.g. "8/10 historical
    # reject decisions" or "author-set").
    rationale: str = ""
    accent: str = ""


class OutcomeSummary(BaseModel):
    """One terminal outcome, ranked in the side panel."""

    id: str  # the outcome node id
    label: str
    outcome_kind: Optional[str] = None
    scenario_id: Optional[str] = None
    probability: float
    # One entry per distinct root->outcome path (a DAG terminal can be
    # reached by more than one path once scenarios are composed). Each entry
    # is the ordered list of edge ids along that path.
    path_edge_ids: list[list[str]] = Field(default_factory=list)


class OutcomePlan(BaseModel):
    question: str
    scenario_ids: list[str]
    nodes: list[OutcomeNode] = Field(default_factory=list)
    edges: list[OutcomeEdge] = Field(default_factory=list)
    outcomes: list[OutcomeSummary] = Field(default_factory=list)
    # Free-form counters: {"nodes", "edges", "outcomes", "paths",
    # "total_probability"}.
    stats: dict[str, float] = Field(default_factory=dict)
