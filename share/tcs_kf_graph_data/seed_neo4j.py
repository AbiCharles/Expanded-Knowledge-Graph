"""Apply seed_neo4j.cypher against the configured Neo4j instance.

Run from the repo root:

    source .venv/bin/activate
    python3 backend/data/seed_neo4j.py

Connection comes from env vars (matching what the backend reads at boot):

    NEO4J_URI       — defaults to bolt://localhost:7687
    NEO4J_USER      — defaults to neo4j
    NEO4J_PASSWORD  — required; falls back to the local docker-compose default

Splits the .cypher script on `;` statement separators and runs each
statement in its own transaction (Cypher does not support multi-statement
scripts via the official driver). Comment lines are stripped.

Idempotent: the first statement is `MATCH (n) DETACH DELETE n;` so a fresh
seed always replaces existing data.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from neo4j import GraphDatabase

CYPHER_FILE = Path(__file__).resolve().parent / "seed_neo4j.cypher"


def _split_statements(text: str) -> list[str]:
    """Split a Cypher script into individual statements.

    The driver runs one Cypher statement at a time. The file uses `;` as
    the statement separator (Neo4j Browser convention) and `//` for
    single-line comments. We strip comments, then split on top-level `;`.
    Not a full parser — works because the seed file has no semicolons
    inside string literals or property maps.
    """
    out: list[str] = []
    buf: list[str] = []
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].rstrip()
        if not line.strip():
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            stmt = "\n".join(buf).rstrip(" ;\n")
            if stmt:
                out.append(stmt)
            buf = []
    if buf:
        leftover = "\n".join(buf).rstrip(" ;\n")
        if leftover:
            out.append(leftover)
    return out


def main() -> int:
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pw = os.environ.get(
        "NEO4J_PASSWORD",
        # Default matches the docker-compose.yaml's seeded password so the
        # script "just works" against the local Neo4j out of the box.
        "YcV7wquQWdFLKZDRwck3CqlbD0W_c1fAV0U2cpMl578",
    )

    text = CYPHER_FILE.read_text(encoding="utf-8")
    statements = _split_statements(text)
    print(f"Connecting to {uri} as {user}")
    print(f"About to apply {len(statements)} Cypher statements from {CYPHER_FILE.name}")

    driver = GraphDatabase.driver(uri, auth=(user, pw))
    try:
        with driver.session() as session:
            for i, stmt in enumerate(statements, start=1):
                try:
                    session.run(stmt)
                except Exception as exc:  # noqa: BLE001
                    print(f"FAILED at statement {i}/{len(statements)}: {exc}")
                    print(f"  >>> {stmt[:200]}")
                    return 1
        # Summary probe
        with driver.session() as session:
            counts = session.run(
                "MATCH (n) WITH labels(n)[0] AS lbl, count(*) AS c "
                "RETURN lbl, c ORDER BY lbl"
            ).data()
            rel_counts = session.run(
                "MATCH ()-[r]->() WITH type(r) AS t, count(*) AS c "
                "RETURN t, c ORDER BY t"
            ).data()
        print()
        print("Node counts by label:")
        for row in counts:
            print(f"  {row['lbl']}: {row['c']}")
        print()
        print("Relationship counts by type:")
        for row in rel_counts:
            print(f"  {row['t']}: {row['c']}")
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
