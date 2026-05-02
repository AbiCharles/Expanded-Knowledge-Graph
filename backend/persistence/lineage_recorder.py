"""SQLite-backed LineageRecorder. Implements the framework's LineageRecorder
Protocol so it can be passed into HITLContextService directly."""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from tcs_hitl_context import LineageEvent, Stage
from tcs_hitl_context.models import KnowledgeRef

from .db import Database, LineageRow

log = logging.getLogger(__name__)


class SqliteLineageRecorder:
    """Append-only persistence of LineageEvents."""

    def __init__(self, db: Database):
        self._db = db

    def record(self, case_id: str, event: LineageEvent) -> None:
        with self._db.session() as session:
            session.add(
                LineageRow(
                    case_id=case_id,
                    sequence=event.sequence,
                    stage=event.stage.value,
                    actor=event.actor,
                    action=event.action,
                    timestamp=event.timestamp,
                    detail=event.detail,
                    knowledge_refs=[
                        ref.model_dump(mode="json") for ref in event.knowledge_refs
                    ],
                )
            )
            session.commit()

    def history(self, case_id: str) -> list[LineageEvent]:
        with self._db.session() as session:
            rows = session.execute(
                select(LineageRow).where(LineageRow.case_id == case_id).order_by(LineageRow.sequence)
            ).scalars().all()
        return [_row_to_event(r) for r in rows]


def _row_to_event(row: LineageRow) -> LineageEvent:
    return LineageEvent(
        sequence=row.sequence,
        stage=Stage(row.stage),
        actor=row.actor,
        action=row.action,
        timestamp=row.timestamp,
        detail=row.detail,
        knowledge_refs=[KnowledgeRef(**ref) for ref in (row.knowledge_refs or [])],
    )
