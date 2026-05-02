"""SQLAlchemy engine + schema."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

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
    phase = Column(String, nullable=False, index=True)
    decision_kind = Column(String, nullable=True, index=True)
    prompt = Column(Text, nullable=False)
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
    def __init__(self, path: Path):
        self._path = path
        self._engine: Engine = create_engine(
            f"sqlite:///{path}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self._engine)

    @property
    def engine(self) -> Engine:
        return self._engine

    def session(self) -> Session:
        return Session(self._engine, expire_on_commit=False)


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
    global _singleton
    _singleton = None
