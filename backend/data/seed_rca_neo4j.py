"""Seed the RCA evidence graph into Neo4j (env-driven, idempotent).

Reads NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD from the environment (the same
secrets the fabric's neo4j_default uses) and applies
`backend/data/seed_rca_neo4j.cypher`. Safe to re-run — every statement is a
MERGE. Runs BEFORE (or after) the supply-chain seed without conflict.

Local:  NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=... \
          python3 backend/data/seed_rca_neo4j.py
Fly:    fly ssh console -a tcs-knowledge-fabric \
          -C "python3 backend/data/seed_rca_neo4j.py"
"""
from __future__ import annotations

import os
from pathlib import Path

CYPHER = Path(__file__).resolve().parent / "seed_rca_neo4j.cypher"


def _statements(text: str) -> list[str]:
    # Drop whole-line // comments, then split on ';' (statements are multi-line).
    body = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("//"))
    return [s.strip() for s in body.split(";") if s.strip()]


def main() -> None:
    from neo4j import GraphDatabase

    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pw = os.environ.get("NEO4J_PASSWORD", "")
    stmts = _statements(CYPHER.read_text(encoding="utf-8"))
    driver = GraphDatabase.driver(uri, auth=(user, pw) if user else None)
    try:
        with driver.session() as session:
            for st in stmts:
                session.run(st)
        print(f"seeded {len(stmts)} RCA statement(s) into {uri}")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
