"""Seed the manufacturing-RCA governance store (rca.sqlite).

Run from the repo root: `python backend/data/seed_rca.py`.

Creates two tables:
  - capa_records : append-only log of CAPAs issued by the issue_capa action
                   (the write target for SC-RCA-DEFECT-001's _executor). The
                   compensation executor flips status → 'voided' by case_id.
  - prior_capa   : historical CAPA precedent, retrieved by the review stage
                   (manufacturing_rca.PriorCAPA) to give the quality lead
                   precedent for defect_type = 'delamination' etc.

Idempotent: DROPs and recreates both tables, then re-seeds prior_capa. The
capa_records table starts empty — the demo populates it on approval.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "rca.sqlite"

PRIOR_CAPA_ROWS = [
    # capa_id, defect_type, root_cause, action, outcome
    ("CAPA-2025-041", "delamination",
     "Autoclave pressure regulator drift caused low consolidation pressure",
     "Replaced regulator; added weekly regulator calibration check",
     "effective — no recurrence in 9 months"),
    ("CAPA-2025-017", "delamination",
     "Vacuum bag leak during layup on bay 3",
     "Introduced dual-stage bag integrity check before cure",
     "effective — leak escapes down 80%"),
    ("CAPA-2024-088", "delamination",
     "Prepreg out-life exceeded before cure",
     "Tightened freezer-out tracking with barcode scan at layup",
     "partially effective — one recurrence, process retrained"),
    ("CAPA-2025-033", "porosity",
     "Resin viscosity out of spec for incoming batch",
     "Added incoming-batch viscosity gate at receiving",
     "effective"),
]


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS capa_records")
        cur.execute("DROP TABLE IF EXISTS prior_capa")
        cur.execute(
            """
            CREATE TABLE capa_records (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id     TEXT,
                defect_id   TEXT,
                part_id     TEXT,
                root_cause  TEXT,
                capa_action TEXT,
                issued_by   TEXT,
                program     TEXT,
                status      TEXT DEFAULT 'issued',
                created_at  TEXT DEFAULT (datetime('now'))
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE prior_capa (
                capa_id     TEXT PRIMARY KEY,
                defect_type TEXT,
                root_cause  TEXT,
                action      TEXT,
                outcome     TEXT
            )
            """
        )
        cur.executemany(
            "INSERT INTO prior_capa (capa_id, defect_type, root_cause, action, outcome) "
            "VALUES (?, ?, ?, ?, ?)",
            PRIOR_CAPA_ROWS,
        )
        conn.commit()
        print(f"seeded {DB_PATH} — prior_capa: {len(PRIOR_CAPA_ROWS)} rows, "
              f"capa_records: empty")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
