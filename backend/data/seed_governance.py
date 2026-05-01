"""(Re)create backend/data/governance.sqlite with realistic prior cases.

Run from the repo root: `python backend/data/seed_governance.py`.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "governance.sqlite"

CASES = [
    # SC-TC-007 — trade override prior cases
    ("PR-2026-Q1-088", "SC-TC-007", "rejected", "End-user could not be verified", "compliance.officer.kchen", 30),
    ("PR-2026-Q1-061", "SC-TC-007", "approved_with_conditions", "Customer provided valid OFAC license; license number recorded", "compliance.officer.kchen", 55),
    ("PR-2025-Q4-217", "SC-TC-007", "rejected", "Pattern of override requests from same customer; escalated to legal", "legal.counsel.rmehta", 110),
    ("PR-2025-Q4-184", "SC-TC-007", "approved", "Standalone case; full diligence package on file", "compliance.officer.tnguyen", 134),
    # SC-PP-007 — vendor onboarding prior cases
    ("PR-2026-Q1-105", "SC-PP-007", "approved", "ISO 9001 audit clean; ESG above threshold", "procurement.lead.amorales", 22),
    ("PR-2026-Q1-073", "SC-PP-007", "rejected", "Capacity assessment insufficient for tier-1 commitment", "procurement.lead.amorales", 48),
    ("PR-2025-Q4-291", "SC-PP-007", "more_info_requested", "Reference customer interviews requested before re-review", "procurement.lead.amorales", 89),
    ("PR-2025-Q3-152", "SC-PP-007", "approved", "Strong financials; sole-source risk acknowledged in record", "procurement.lead.amorales", 178),
    # SC-LN-002 — mode-switch prior cases
    ("PR-2026-Q1-211", "SC-LN-002", "approved", "Customer SLA exposure justified one-time air upgrade", "logistics.planner.lead", 18),
    ("PR-2026-Q1-189", "SC-LN-002", "rejected", "Recurring lane pattern; structural review required first", "logistics.planner.lead", 35),
    ("PR-2025-Q4-322", "SC-LN-002", "rejected", "Cost recovery insufficient given budget envelope", "logistics.planner.lead", 122),
    ("PR-2025-Q4-298", "SC-LN-002", "approved", "Force majeure event upstream; one-time exception granted", "logistics.planner.lead", 145),
]

DDL = """
CREATE TABLE IF NOT EXISTS prior_cases (
    case_id      TEXT PRIMARY KEY,
    scenario_id  TEXT NOT NULL,
    outcome      TEXT NOT NULL,
    rationale    TEXT NOT NULL,
    decided_by   TEXT NOT NULL,
    decided_at   TEXT NOT NULL  -- ISO date
);
CREATE INDEX IF NOT EXISTS idx_prior_cases_scenario ON prior_cases(scenario_id);
"""


def main() -> None:
    DB_PATH.unlink(missing_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(DDL)
    today = datetime.utcnow()
    rows = [
        (
            cid, sid, outcome, rationale, decided_by,
            (today - timedelta(days=days_ago)).date().isoformat(),
        )
        for cid, sid, outcome, rationale, decided_by, days_ago in CASES
    ]
    conn.executemany(
        "INSERT INTO prior_cases (case_id, scenario_id, outcome, rationale, decided_by, decided_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"Wrote {len(rows)} rows to {DB_PATH}")


if __name__ == "__main__":
    main()
