"""SQLAlchemy engine + schema for cases, lineage events, and users.

One SQLite file at ``backend/data/app.sqlite``. The engine, the
declarative ``Base``, and three ORM row classes are defined here.
``get_database(path)`` is the lazy singleton callers use at runtime.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Engine,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    pass


class CaseRow(Base):
    """One row per CaseRecord. Payload is the JSON-serialised CaseRecord
    minus the asyncio.Event (which doesn't serialise and is only meaningful
    for in-flight cases)."""
    __tablename__ = "cases"

    case_id = Column(String, primary_key=True)
    scenario_id = Column(String, nullable=True, index=True)
    # Immutable scenario version this case was created against. Null for
    # cases created before the versioning migration ran.
    scenario_version = Column(Integer, nullable=True)
    phase = Column(String, nullable=False, index=True)
    decision_kind = Column(String, nullable=True, index=True)
    prompt = Column(Text, nullable=False)
    # Owner — null for cases created before auth was on (treated as system-owned).
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # The framework's internal KnowledgeContext.case_id; lineage events are
    # keyed by this. Indexed so we can JOIN cases ↔ lineage_events for metrics.
    framework_case_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    payload = Column(JSON, nullable=False)  # full CaseRecord dict


class LineageRow(Base):
    """One row per LineageEvent. case_id has an index for replay queries."""
    __tablename__ = "lineage_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String, ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    stage = Column(String, nullable=False, index=True)
    actor = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    detail = Column(Text, nullable=True)
    knowledge_refs = Column(JSON, nullable=False, default=list)


class CaseHighlightedFactRow(Base):
    """Phase 2 — flat, queryable record of "facts the reviewer flagged as
    load-bearing" per decided case.

    Denormalised on purpose: Phase 3's pattern-mining will GROUP BY
    `(scenario_id, scenario_version, decision_kind, fact_ontology_type)`
    to find recurring override drivers. A JSON blob on `cases.payload`
    is fine for read-back, but the aggregates need columns + indexes.

    Insert-only — when a case is replayed or its decision changes (which
    today only happens via the rare admin endpoint), the previous rows
    for that case are deleted before the new ones are written, so
    `(case_id, position)` is effectively unique."""
    __tablename__ = "case_highlighted_facts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String, ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False, index=True)
    # Snapshot of the case's scenario + version at decision time, so
    # Phase 3 can mine patterns per `(scenario_id, version)` without a
    # join back to cases (and so the row survives a later case mutation).
    scenario_id = Column(String, nullable=False, index=True)
    scenario_version = Column(Integer, nullable=True)
    decision_kind = Column(String, nullable=False, index=True)
    # The fact's (source, ontology_type, id) triple — matches KnowledgeRef
    # exactly. Reviewer-supplied title kept for cheap UI render.
    fact_source = Column(String, nullable=False)
    fact_ontology_type = Column(String, nullable=False, index=True)
    fact_id = Column(String, nullable=False)
    fact_title = Column(Text, nullable=True)
    # 0..2 — preserves the order the reviewer picked. Useful when later
    # tooling wants "the most load-bearing fact."
    position = Column(Integer, nullable=False)
    highlighted_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class UserRow(Base):
    """Users table — populated by the auth iteration. Schema declared now so
    we don't migrate later."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=True)
    role = Column(String, nullable=False, default="operator")  # operator | reviewer | admin
    display_name = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Database:
    """Thin wrapper around a single SQLAlchemy engine + session factory.

    One instance per process. Initialised at app startup with the path to
    the SQLite file; subsequent code uses ``get_database()`` to access the
    same singleton.
    """

    def __init__(self, path: Path):
        """Open the SQLite file at ``path``, create tables, run migrations.

        ``check_same_thread=False`` is required for FastAPI's threadpool —
        each request can run on a different worker thread.
        """
        self._path = path
        self._engine: Engine = create_engine(
            f"sqlite:///{path}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self._engine)
        self._micro_migrate()

    @property
    def engine(self) -> Engine:
        """Underlying SQLAlchemy engine — exposed for advanced callers."""
        return self._engine

    def session(self) -> Session:
        """New session bound to this engine. Use as a context manager."""
        return Session(self._engine, expire_on_commit=False)

    def _micro_migrate(self) -> None:
        """Add columns we've introduced after the original schema.

        SQLite's ``ALTER TABLE ADD COLUMN`` is non-destructive; we run each
        statement once and roll back the duplicate-column / duplicate-index
        errors on subsequent boots. Real Alembic migrations would be
        overkill for this single-file demo.
        """
        from sqlalchemy import text
        for stmt in [
            "ALTER TABLE cases ADD COLUMN user_id INTEGER",
            "ALTER TABLE cases ADD COLUMN framework_case_id TEXT",
            "CREATE INDEX IF NOT EXISTS idx_cases_framework_case_id ON cases(framework_case_id)",
            "ALTER TABLE cases ADD COLUMN scenario_version INTEGER",
            # Phase 2 — composite index for the Phase 3 mining query
            # `GROUP BY scenario_id, decision_kind, fact_ontology_type`.
            (
                "CREATE INDEX IF NOT EXISTS idx_case_highlighted_facts_mining "
                "ON case_highlighted_facts(scenario_id, decision_kind, fact_ontology_type)"
            ),
        ]:
            with self._engine.connect() as conn:
                try:
                    conn.execute(text(stmt))
                    conn.commit()
                except Exception as exc:  # noqa: BLE001
                    # Expected on subsequent boots ("duplicate column" / etc.)
                    log.debug("micro-migrate %r already applied: %s", stmt, exc)
                    conn.rollback()


_singleton: Optional[Database] = None


def get_database(path: Optional[Path] = None) -> Database:
    """Lazy singleton — main.py calls this once at startup with the right path."""
    global _singleton
    if _singleton is None:
        if path is None:
            raise RuntimeError("Database not initialised; call get_database(path) at startup")
        _singleton = Database(path)
    return _singleton


def reset_database_for_tests() -> None:
    """Drop the singleton so the next ``get_database(path)`` call rebinds.

    Used only by tests; never call this from request-handling code.
    """
    global _singleton
    _singleton = None
