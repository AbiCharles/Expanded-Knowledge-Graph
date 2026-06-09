"""Persistent case store.

Wraps an in-memory `dict[str, CaseRecord]` and mirrors writes to SQLite.
Design notes:

- The dict is kept for hot access — `state.cases[id]` lookups stay O(1) and
  asyncio.Event objects (used to signal review decisions) live on the
  in-memory record.
- Every mutation (`__setitem__`, `pop`, `save`) writes through to SQLite.
- On startup, `load_all()` rehydrates the dict from SQLite (without
  asyncio.Event — those are only meaningful for in-flight cases, and any
  in-flight case is dead after a restart anyway).

This keeps the CaseRecord type unchanged and the rest of the app oblivious
to whether persistence is on or off.
"""
from __future__ import annotations

import logging
from typing import Iterator, Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..case_record import CaseRecord
from .db import CaseRow, Database

log = logging.getLogger(__name__)


def _record_to_payload(rec: CaseRecord) -> dict:
    """Serialise a CaseRecord (minus the asyncio.Event)."""
    return {
        "case_id": rec.case_id,
        "prompt": rec.prompt,
        "scenario_id": rec.scenario_id,
        "scenario_version": rec.scenario_version,
        "interpreted_as": rec.interpreted_as,
        "clarifying_question": rec.clarifying_question,
        "user_id": rec.user_id,
        "confidence": rec.confidence,
        "candidates": rec.candidates,
        "phase": rec.phase,
        "framework_case_id": rec.framework_case_id,
        "ticket_id": rec.ticket_id,
        "decision_kind": rec.decision_kind,
        "rationale": rec.rationale,
        "follow_up": rec.follow_up,
        "sibling_case_ids": rec.sibling_case_ids,
        "replay_decision": rec.replay_decision,
        "closing_message": rec.closing_message,
    }


def _payload_to_record(payload: dict) -> CaseRecord:
    return CaseRecord(
        case_id=payload["case_id"],
        prompt=payload.get("prompt", ""),
        scenario_id=payload.get("scenario_id"),
        scenario_version=payload.get("scenario_version"),
        interpreted_as=payload.get("interpreted_as"),
        clarifying_question=payload.get("clarifying_question"),
        user_id=payload.get("user_id"),
        confidence=float(payload.get("confidence", 0.0)),
        candidates=list(payload.get("candidates", []) or []),
        phase=payload.get("phase", "complete"),
        framework_case_id=payload.get("framework_case_id"),
        ticket_id=payload.get("ticket_id"),
        decision_kind=payload.get("decision_kind"),
        rationale=payload.get("rationale"),
        follow_up=payload.get("follow_up"),
        sibling_case_ids=list(payload.get("sibling_case_ids", []) or []),
        replay_decision=payload.get("replay_decision"),
        closing_message=payload.get("closing_message"),
        # ctx is not persisted — it's derived from lineage on demand. For our
        # demo, in-flight ctx is lost on restart, but that's fine.
    )


class PersistentCaseStore:
    """Dict-like cache backed by SQLite.

    Implements the subset of dict operations the orchestrator and API actually
    use: `__getitem__`, `__setitem__`, `__delitem__`, `__contains__`,
    `__iter__`, `get`, `pop`, `values`. Each write mirrors to SQLite.
    """

    def __init__(self, db: Database):
        self._db = db
        self._cache: dict[str, CaseRecord] = {}
        self._load_all()

    def _load_all(self) -> None:
        with self._db.session() as session:
            rows = session.execute(select(CaseRow)).scalars().all()
        for row in rows:
            try:
                self._cache[row.case_id] = _payload_to_record(row.payload or {})
            except Exception:
                log.exception("could not rehydrate case %s; skipping", row.case_id)
        log.info("loaded %d persisted case(s)", len(self._cache))

    def save(self, rec: CaseRecord) -> None:
        """Idempotent upsert — call after every meaningful mutation."""
        payload = _record_to_payload(rec)
        with self._db.session() as session:
            stmt = sqlite_insert(CaseRow.__table__).values(
                case_id=rec.case_id,
                scenario_id=rec.scenario_id,
                scenario_version=rec.scenario_version,
                phase=rec.phase,
                decision_kind=rec.decision_kind,
                prompt=rec.prompt,
                user_id=rec.user_id,
                framework_case_id=rec.framework_case_id,
                payload=payload,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[CaseRow.case_id],
                set_={
                    "scenario_id": rec.scenario_id,
                    "scenario_version": rec.scenario_version,
                    "phase": rec.phase,
                    "decision_kind": rec.decision_kind,
                    "prompt": rec.prompt,
                    "user_id": rec.user_id,
                    "framework_case_id": rec.framework_case_id,
                    "payload": payload,
                },
            )
            session.execute(stmt)
            session.commit()

    # ---- dict-protocol surface --------------------------------------------
    def __setitem__(self, key: str, rec: CaseRecord) -> None:
        self._cache[key] = rec
        self.save(rec)

    def __getitem__(self, key: str) -> CaseRecord:
        return self._cache[key]

    def __delitem__(self, key: str) -> None:
        self._cache.pop(key, None)
        with self._db.session() as session:
            row = session.get(CaseRow, key)
            if row is not None:
                session.delete(row)
                session.commit()

    def __contains__(self, key: str) -> bool:
        return key in self._cache

    def __iter__(self) -> Iterator[str]:
        return iter(self._cache)

    def __len__(self) -> int:
        return len(self._cache)

    def get(self, key: str, default=None) -> Optional[CaseRecord]:
        return self._cache.get(key, default)

    def pop(self, key: str, default=None):
        rec = self._cache.pop(key, default)
        with self._db.session() as session:
            row = session.get(CaseRow, key)
            if row is not None:
                session.delete(row)
                session.commit()
        return rec

    def values(self):
        return self._cache.values()

    def items(self):
        return self._cache.items()
