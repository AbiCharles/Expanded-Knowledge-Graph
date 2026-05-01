"""
Lineage — append-only audit trail for every fetch, bind, submit, and decision
event. Production deployments replace this with a write to the governance
audit store (e.g., immutable log on object storage + index in the Customs
audit DB used by SC-CU-007).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from .models import LineageEvent, Stage
from .protocols import LineageRecorder


class InMemoryLineageRecorder(LineageRecorder):
    """Default recorder — fine for tests and reference; not durable."""

    def __init__(self):
        self._log: dict[str, list[LineageEvent]] = defaultdict(list)

    def record(self, case_id: str, event: LineageEvent) -> None:
        event.sequence = len(self._log[case_id])
        self._log[case_id].append(event)

    def history(self, case_id: str) -> list[LineageEvent]:
        return list(self._log.get(case_id, []))


def make_event(
    *,
    stage: Stage,
    actor: str,
    action: str,
    knowledge_refs: Optional[list] = None,
    detail: Optional[str] = None,
) -> LineageEvent:
    return LineageEvent(
        sequence=0,  # set by recorder
        stage=stage,
        actor=actor,
        action=action,
        knowledge_refs=knowledge_refs or [],
        detail=detail,
    )
