"""Single CaseRecord type used across state, persistence, orchestrator.

Lives in its own module to avoid the circular import that arises when
`persistence/case_store.py` and `state.py` both want to refer to it.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from tcs_hitl_context import KnowledgeContext


@dataclass
class CaseRecord:
    """One operator-initiated case + everything needed to resume it.

    `phase` mirrors the frontend's state machine and is the source of truth
    for what the UI should show.
    """

    case_id: str
    prompt: str
    scenario_id: Optional[str]
    # The immutable scenario version this case ran against. Stamped at
    # case-creation time from the live scenario's `version` field, so a
    # later edit (which would bump to v+1) doesn't retroactively change
    # what this case was tested under. Null for cases created before the
    # versioning migration shipped.
    scenario_version: Optional[int] = None
    interpreted_as: Optional[str] = None
    clarifying_question: Optional[str] = None
    user_id: Optional[int] = None  # owner; None for legacy cases pre-auth
    confidence: float = 0.0
    candidates: list[dict] = field(default_factory=list)  # [{scenario_id, title, confidence}]
    phase: str = "awaiting_clarification"
    # awaiting_clarification | binding | review_ready | reviewing | complete | cancelled
    ctx: Optional[KnowledgeContext] = None
    # The framework's KnowledgeContext.case_id is its own UUID (different from
    # ours). We capture it here so lineage can be looked up after restart when
    # ctx is None.
    framework_case_id: Optional[str] = None
    ticket_id: Optional[str] = None
    decision_kind: Optional[str] = None  # approve | reject | request_more_info | auto_execute | no_op
    rationale: Optional[str] = None
    follow_up: Optional[str] = None
    sibling_case_ids: list[str] = field(default_factory=list)
    replay_decision: Optional[str] = None
    closing_message: Optional[str] = None
    # asyncio.Event signalling that a decision has been recorded for this case's ticket
    decision_event: Optional[asyncio.Event] = None
    # When a scenario wires an `_executor` block, the orchestrator invokes
    # the named action's executor and stashes the outcome here so the
    # case-detail endpoint can render it.
    execution_result: Optional[dict] = None
    # Phase 2 — structured override capture. Optional reviewer-flagged
    # facts that were load-bearing in the decision. Each item is
    # `{source, ontology_type, id, title?}`; the (source, ontology_type,
    # id) triple matches the fact's KnowledgeRef so Phase 3 can join.
    # Capped at 3 by the API to keep the signal sharp. Empty list when
    # the reviewer didn't single anything out (or for autonomous cases
    # where there's no reviewer to ask).
    highlighted_fact_refs: list[dict] = field(default_factory=list)
