"""SQLite persistence for cases, lineage, and (later) users.

Single SQLite file at `backend/data/app.sqlite`. Tables:

  cases            one row per CaseRecord, JSON-encoded payload
  lineage_events   append-only audit log
  users            (added in the auth iteration; empty table for now)

Why SQLite, not Postgres? Single-process FastAPI demo; one file, no infra,
no migrations. The seam is small enough that swapping to Postgres later is
~20 lines (change the engine URL, add asyncpg).
"""
from .db import Database, get_database
from .lineage_recorder import SqliteLineageRecorder
from .case_store import PersistentCaseStore

__all__ = [
    "Database",
    "get_database",
    "SqliteLineageRecorder",
    "PersistentCaseStore",
]
