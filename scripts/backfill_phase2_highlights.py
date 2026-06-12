#!/usr/bin/env python3
"""Phase 2 backfill — populate `case_highlighted_facts` for cases that
closed before Phase 2 shipped.

There is no reliable way to know which facts the reviewer would have
flagged retroactively — Phase 2 captures something the UI never asked
for before. So this script only does what it can do honestly:

    skip   (default)  Don't backfill anything; print how many cases are
                      eligible so you know how much "ground truth" you're
                      leaving empty for Phase 3 to mine later.
    demo              Seed canonical highlights for hard-coded demo case
                      ids (SC-PP-008 etc.) so the UI surface has
                      something to render for new audiences. Whoever
                      curates the seeds (a category manager / SME) owns
                      the mapping — see DEMO_SEEDS below.

Pass --apply to actually write. Otherwise prints what would happen.

    python scripts/backfill_phase2_highlights.py
    python scripts/backfill_phase2_highlights.py --mode demo
    python scripts/backfill_phase2_highlights.py --mode demo --apply
    python scripts/backfill_phase2_highlights.py --mode demo --apply --db /path/to/app.sqlite
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


# Curated seed map — only used in --mode demo. Each entry says: when
# we're showing this case in a demo, render these facts as if the
# reviewer had flagged them. Picked by an SME, not derived.
#
# IMPORTANT: every closed case of `scenario_id` gets the SAME seeds.
# That's fine for "make the demo UI look populated" but it inflates
# Phase 3 pattern confidence if these rows are mined. Treat as cosmetic
# data, not reviewer signal.
DEMO_SEEDS: dict[str, list[dict[str, Any]]] = {
    # Supplier onboarding — sanctions proximity + carrier concentration
    # drove the canonical reject case. Tier-1 reliability score made up
    # the third leg in the deck's narrative.
    "SC-PP-008": [
        {"source": "graph:neo4j_default", "ontology_type": "SanctionsProximity",
         "id": "SUP-001-PROX", "title": "3-hop indirect ownership of OFAC SDN entity"},
        {"source": "graph:neo4j_default", "ontology_type": "CarrierExposure",
         "id": "SUP-001-CARRIER", "title": "All preferred carriers in one alliance"},
        {"source": "sqlite:governance_sqlite", "ontology_type": "PriorOverride",
         "id": "C-PP-007-001", "title": "Prior reject on similar tier-1 candidate"},
    ],
    # Mode-switch ocean → air on a critical lane. The planner cited the
    # prior reroute precedent + the upcoming customer SLA window.
    "SC-LN-002": [
        {"source": "sqlite:governance_sqlite", "ontology_type": "PriorOverride",
         "id": "C-LN-002-001", "title": "Prior reroute approved on same lane"},
        {"source": "sqlite:logistics_sqlite", "ontology_type": "FreightRate",
         "id": "FR-LHCA-AIR-001", "title": "Air rate within recovery envelope (+18%)"},
    ],
    # Ultimate Beneficial Owner disclosure — the ownership walk turned
    # up a tier-3 holding company the supplier hadn't declared.
    "SC-PP-UBO-023": [
        {"source": "graph:neo4j_default", "ontology_type": "UltimateBeneficialOwner",
         "id": "UBO-APEX-HOLDINGS", "title": "Undisclosed tier-3 owner: Apex Holdings"},
        {"source": "sqlite:governance_sqlite", "ontology_type": "PriorOverride",
         "id": "C-PP-UBO-PRIOR", "title": "Prior request-more-info on similar gap"},
    ],
}

def ensure_schema(conn: sqlite3.Connection) -> None:
    """Idempotent: create case_highlighted_facts + index if the target DB
    predates Phase 2. The backend's _micro_migrate does this on startup,
    but the script can be aimed at a cold sqlite that hasn't been opened
    by the app yet (e.g. a prod snapshot copied locally).

    Also runs the Phase 1 ALTER TABLEs so the SELECT below works on a
    cold DB that predates Phase 1 too."""
    # Phase 1 columns the SELECT below depends on. Duplicate-column
    # errors on a Phase-1-already-migrated DB are expected; swallow them.
    for stmt in (
        "ALTER TABLE cases ADD COLUMN scenario_version INTEGER",
        "ALTER TABLE cases ADD COLUMN framework_case_id TEXT",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS case_highlighted_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            scenario_id TEXT NOT NULL,
            scenario_version INTEGER,
            decision_kind TEXT NOT NULL,
            fact_source TEXT NOT NULL,
            fact_ontology_type TEXT NOT NULL,
            fact_id TEXT NOT NULL,
            fact_title TEXT,
            position INTEGER NOT NULL,
            highlighted_at DATETIME NOT NULL,
            FOREIGN KEY(case_id) REFERENCES cases(case_id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_case_highlighted_facts_mining "
                 "ON case_highlighted_facts(scenario_id, decision_kind, fact_ontology_type)")


def fetch_eligible_cases(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Closed cases that have NO highlights row yet."""
    rows = conn.execute(
        """
        SELECT c.case_id, c.scenario_id, c.scenario_version, c.decision_kind, c.payload
          FROM cases c
          LEFT JOIN case_highlighted_facts h ON h.case_id = c.case_id
         WHERE c.decision_kind IS NOT NULL
           AND h.id IS NULL
        """
    ).fetchall()
    out = []
    for r in rows:
        try:
            payload = json.loads(r[4]) if isinstance(r[4], str) else (r[4] or {})
        except json.JSONDecodeError:
            payload = {}
        out.append({
            "case_id": r[0],
            "scenario_id": r[1],
            "scenario_version": r[2],
            "decision_kind": r[3],
            "payload": payload,
        })
    return out


def write_highlights(
    conn: sqlite3.Connection,
    case: dict[str, Any],
    refs: list[dict[str, Any]],
) -> None:
    """Insert one row per ref + sync the case payload's
    `highlighted_fact_refs` so the API read-back matches."""
    now = datetime.utcnow().isoformat(timespec="seconds")
    for position, ref in enumerate(refs):
        conn.execute(
            """
            INSERT INTO case_highlighted_facts
                (case_id, scenario_id, scenario_version, decision_kind,
                 fact_source, fact_ontology_type, fact_id, fact_title,
                 position, highlighted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case["case_id"], case["scenario_id"], case["scenario_version"],
                case["decision_kind"], ref["source"], ref["ontology_type"],
                ref["id"], ref.get("title"), position, now,
            ),
        )
    # Echo into the JSON payload so /api/cases/{id} round-trips correctly.
    new_payload = dict(case["payload"])
    new_payload["highlighted_fact_refs"] = refs
    conn.execute(
        "UPDATE cases SET payload = ? WHERE case_id = ?",
        (json.dumps(new_payload), case["case_id"]),
    )


# -----------------------------------------------------------------------------
# Mode handlers
# -----------------------------------------------------------------------------
def run_skip(eligible: list[dict[str, Any]]) -> int:
    print(f"  {len(eligible)} closed case(s) have no highlights.")
    print("  Skipping all backfill — Phase 3 mining will treat these as "
          "'no reviewer signal' (which is honest: nobody was ever asked).")
    return 0


def run_demo(
    conn: sqlite3.Connection, eligible: list[dict[str, Any]], apply: bool,
) -> int:
    written = 0
    by_scenario: dict[str, int] = {}
    for case in eligible:
        seeds = DEMO_SEEDS.get(case["scenario_id"] or "")
        if not seeds:
            continue
        action = "WRITE" if apply else "would write"
        print(f"  {action} {len(seeds)} highlight(s) for {case['case_id']} "
              f"({case['scenario_id']} · {case['decision_kind']}):")
        for ref in seeds:
            print(f"    · {ref['ontology_type']:25s} {ref['id']:30s}  {ref.get('title', '')}")
        if apply:
            write_highlights(conn, case, seeds)
            written += len(seeds)
        by_scenario[case["scenario_id"] or "?"] = by_scenario.get(
            case["scenario_id"] or "?", 0) + len(seeds)
    print()
    if not by_scenario:
        print("  No cases matched the curated demo-seeds map. Add an entry to "
              "DEMO_SEEDS for any scenario you want populated.")
    else:
        print(f"  Per-scenario: {by_scenario}")
    return written


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=Path("backend/data/app.sqlite"),
                    help="Path to the case sqlite (default: backend/data/app.sqlite)")
    ap.add_argument("--mode", choices=("skip", "demo"), default="skip",
                    help="Backfill strategy (default: skip — does nothing)")
    ap.add_argument("--apply", action="store_true",
                    help="Actually write. Without --apply this is dry-run.")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"error: {args.db} does not exist", file=sys.stderr)
        return 2

    with sqlite3.connect(args.db) as conn:
        ensure_schema(conn)
        eligible = fetch_eligible_cases(conn)
        print(f"DB · {args.db}")
        print(f"Mode · {args.mode}  (dry-run)" if not args.apply else f"Mode · {args.mode}  (APPLY)")
        print()
        if args.mode == "skip":
            run_skip(eligible)
            return 0
        n = run_demo(conn, eligible, args.apply)
        if args.apply:
            conn.commit()
            print(f"\nWrote {n} highlight row(s).")
        else:
            print("\n(Dry-run — re-run with --apply to commit.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
