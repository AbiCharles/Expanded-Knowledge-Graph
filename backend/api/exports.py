"""Audit-log exports.

Operators / compliance teams can pull a CSV slice of the lineage and case
history for a date range. Backed by the persisted lineage_events + cases
tables.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, select

from ..persistence.db import CaseRow, LineageRow

router = APIRouter(tags=["exports"])


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    # Accept either YYYY-MM-DD or full ISO
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


@router.get("/exports/lineage.csv")
def export_lineage_csv(
    request: Request,
    start: Optional[str] = Query(None, description="ISO date or datetime"),
    end: Optional[str] = Query(None, description="ISO date or datetime"),
    scenario_id: Optional[str] = Query(None),
):
    """Stream the lineage_events table joined with cases, filtered by date."""
    state = request.app.state.app_state
    db = state.database
    start_dt = _parse_iso(start)
    end_dt = _parse_iso(end)

    def rows():
        with db.session() as session:
            stmt = (
                select(LineageRow, CaseRow)
                .join(CaseRow, CaseRow.case_id == LineageRow.case_id, isouter=True)
                .order_by(LineageRow.timestamp)
            )
            conds = []
            if start_dt is not None:
                conds.append(LineageRow.timestamp >= start_dt)
            if end_dt is not None:
                conds.append(LineageRow.timestamp <= end_dt)
            if scenario_id is not None:
                conds.append(CaseRow.scenario_id == scenario_id)
            if conds:
                stmt = stmt.where(and_(*conds))
            for lineage_row, case_row in session.execute(stmt).all():
                yield lineage_row, case_row

    def generator():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "timestamp", "case_id", "scenario_id", "phase", "decision_kind",
            "stage", "actor", "action", "detail", "knowledge_ref_count",
        ])
        yield buf.getvalue()
        buf.seek(0); buf.truncate(0)

        for lineage_row, case_row in rows():
            writer.writerow([
                lineage_row.timestamp.isoformat() if lineage_row.timestamp else "",
                lineage_row.case_id or "",
                (case_row.scenario_id if case_row else "") or "",
                (case_row.phase if case_row else "") or "",
                (case_row.decision_kind if case_row else "") or "",
                lineage_row.stage or "",
                lineage_row.actor or "",
                lineage_row.action or "",
                (lineage_row.detail or "").replace("\n", " "),
                len(lineage_row.knowledge_refs or []),
            ])
            yield buf.getvalue()
            buf.seek(0); buf.truncate(0)

    filename = "lineage"
    if start:
        filename += f"_{start}"
    if end:
        filename += f"_to_{end}"
    filename += ".csv"
    return StreamingResponse(
        generator(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/exports/cases.csv")
def export_cases_csv(request: Request):
    """One-row-per-case summary."""
    state = request.app.state.app_state
    db = state.database

    def generator():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "case_id", "scenario_id", "phase", "decision_kind",
            "created_at", "updated_at", "prompt",
        ])
        yield buf.getvalue()
        buf.seek(0); buf.truncate(0)

        with db.session() as session:
            for row in session.execute(select(CaseRow).order_by(CaseRow.created_at)).scalars():
                writer.writerow([
                    row.case_id,
                    row.scenario_id or "",
                    row.phase or "",
                    row.decision_kind or "",
                    row.created_at.isoformat() if row.created_at else "",
                    row.updated_at.isoformat() if row.updated_at else "",
                    (row.prompt or "").replace("\n", " "),
                ])
                yield buf.getvalue()
                buf.seek(0); buf.truncate(0)

    return StreamingResponse(
        generator(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="cases.csv"'},
    )
