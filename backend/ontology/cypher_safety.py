"""Read-only Cypher guard.

Refuses any Cypher statement that would mutate the graph. Used by:
  - The Cypher playground endpoint (operator-typed Cypher)
  - The Neo4jResolver when running mapping `query_template` strings
  - Any future LLM→Cypher path

Strategy is conservative regex matching against statement keywords plus
dangerous procedure names. Not a full Cypher parser — false positives
are acceptable, false negatives are not.

Lifted in spirit from the external KnowledgeGraph repo's
`pipeline/cypher_safety.py`. Kept self-contained so the same guard can
be applied uniformly across every Cypher entry point.
"""
from __future__ import annotations

import re

# Statement-level write keywords: any of these appearing as a Cypher clause
# is a write. Boundary-checked so a node label like `:CreatedAt` doesn't
# trip a false positive.
_WRITE_CLAUSE_RE = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH\s+DELETE|SET|REMOVE|DROP|FOREACH|LOAD\s+CSV)\b",
    re.IGNORECASE,
)

# `CALL` itself is fine (procedures like `db.labels()` are read-only). We
# block specific procedure namespaces that mutate or perform side effects.
_DANGEROUS_PROC_RE = re.compile(
    r"\bCALL\s+("
    r"apoc\.(?:create|merge|refactor|nodes\.delete|relationship|periodic"
    r"|trigger|atomic|cypher\.runWrite|export)"
    r"|n10s\.(?:rdf\.import|onto\.import|graphconfig\.init|nsprefixes\.add)"
    r"|gds\.graph\.(?:project|drop|stream)"
    r"|db\.(?:create|drop|index\.fulltext\.create|index\.vector\.create)"
    r")",
    re.IGNORECASE,
)


class CypherSafetyError(ValueError):
    """Raised when a Cypher statement would mutate the graph."""


def assert_read_only(cypher: str, *, source: str = "operator") -> None:
    """Raise CypherSafetyError if `cypher` contains any write clause or
    dangerous procedure call. `source` is included in the error for
    audit clarity (e.g. "operator", "llm", "mapping query_template").
    """
    text = (cypher or "").strip()
    if not text:
        raise CypherSafetyError("empty Cypher rejected")

    # Strip line- and block-comments before keyword scan so a comment like
    # "// CREATE the report" doesn't trip the guard.
    text = re.sub(r"//[^\n]*", " ", text)
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)

    if _WRITE_CLAUSE_RE.search(text):
        raise CypherSafetyError(
            f"Cypher rejected ({source}): statement contains a write clause "
            "(CREATE/MERGE/DELETE/SET/REMOVE/DROP/FOREACH/LOAD CSV)"
        )
    if _DANGEROUS_PROC_RE.search(text):
        raise CypherSafetyError(
            f"Cypher rejected ({source}): call to a write/mutate procedure "
            "(apoc.create/refactor, n10s.rdf.import, gds.graph.project, db.create*)"
        )


def is_read_only(cypher: str) -> bool:
    """Convenience wrapper — returns True if the statement passes the guard."""
    try:
        assert_read_only(cypher)
    except CypherSafetyError:
        return False
    return True
