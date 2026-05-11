"""Neo4j-backed KnowledgeResolver.

The connector is binding-driven: when called via the OntologyResolver,
the binding's `query_template` (a Cypher MATCH … RETURN) is run with the
user's filter dict as named parameters. Without a binding, falls back to
auto-generating a `MATCH (n:<Label>) WHERE n.<id> = $id RETURN n` shape
where `<Label>` defaults to the requested `ontology_type` and `<id>`
comes from `binding.identifier_column`.

Every Cypher path goes through `assert_read_only` from
`backend/ontology/cypher_safety.py` — write clauses (CREATE/MERGE/DELETE/
SET/REMOVE/etc.) and dangerous procedures are rejected before reaching
the driver.

Example source spec:

    id: graph_local
    kind: neo4j
    uri: bolt://localhost:7687
    user: neo4j
    password: password
    database: neo4j      # optional
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from tcs_hitl_context import KnowledgeFact, KnowledgeQuery, KnowledgeRef

# `$param` references in a Cypher template. Used to auto-fill missing
# bindings with None so the optional-filter idiom (`$x IS NULL OR …`)
# works without forcing callers to enumerate every parameter.
_CYPHER_PARAM_RE = re.compile(r"\$([A-Za-z_]\w*)")

# Lazy import inside methods that need it. The ontology package's __init__
# imports schema_introspect → backend.datasources, so a top-level import
# here would create a circular load (registry → neo4j_source → ontology →
# datasources). Deferring resolves it.
def _safety():
    from backend.ontology.cypher_safety import CypherSafetyError, assert_read_only

    return CypherSafetyError, assert_read_only

log = logging.getLogger(__name__)


class Neo4jResolver:
    """KnowledgeResolver backed by a Neo4j Bolt connection.

    The driver is created lazily on first `resolve()` so an
    unreachable Neo4j doesn't crash the registry at import time.
    """

    def __init__(
        self,
        *,
        source_id: str,
        uri: str,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ):
        self.name = source_id
        self._uri = uri
        self._user = user
        self._password = password
        self._database = database
        self._driver: Any = None  # lazy

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------
    def _get_driver(self):
        if self._driver is None:
            from neo4j import GraphDatabase  # local import keeps tests fast

            auth = (self._user, self._password) if self._user else None
            self._driver = GraphDatabase.driver(self._uri, auth=auth)
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.close()
            except Exception:  # noqa: BLE001
                pass
            self._driver = None

    # -------------------------------------------------------------------------
    # KnowledgeResolver Protocol
    # -------------------------------------------------------------------------
    def resolve(self, query: KnowledgeQuery) -> list[KnowledgeFact]:
        binding = query.filters.get("__binding__") or {}
        cypher = binding.get("query_template")
        if not cypher:
            # Auto-derive a minimal MATCH from the requested class + identifier.
            label = query.ontology_type or "Node"
            id_col = binding.get("identifier_column") or "id"
            # If the caller supplied that identifier in the filters, scope by it;
            # otherwise just LIMIT and return everything (capped at max_results).
            params_have_id = id_col in query.filters
            cypher = (
                f"MATCH (n:`{label}`)"
                + (f" WHERE n.`{id_col}` = ${id_col}" if params_have_id else "")
                + " RETURN n LIMIT $max_results"
            )

        CypherSafetyError, assert_read_only = _safety()
        try:
            assert_read_only(cypher, source=f"neo4j_resolver:{self.name}")
        except CypherSafetyError as exc:
            log.warning("Neo4jResolver %s rejected Cypher: %s", self.name, exc)
            return []

        params: dict[str, Any] = {
            k: v
            for k, v in query.filters.items()
            if k not in ("__binding__", "__ontology__")
        }
        params.setdefault("max_results", query.max_results)

        # Cypher refuses to run when a `$param` reference is unbound, even
        # when the template only uses it inside a `$x IS NULL OR …` guard.
        # Auto-fill any `$<name>` referenced in the template that's missing
        # from the filter dict with None so the optional-filter idiom works
        # without callers needing to enumerate every param up-front.
        for name in _CYPHER_PARAM_RE.findall(cypher):
            params.setdefault(name, None)

        try:
            driver = self._get_driver()
            session_kw = {"database": self._database} if self._database else {}
            with driver.session(**session_kw) as session:
                result = session.run(cypher, **params)
                rows = [dict(rec) for rec in result]
        except Exception as exc:  # noqa: BLE001
            log.warning("Neo4jResolver %s query failed: %s", self.name, exc)
            return []

        return [
            self._row_to_fact(row, query.ontology_type, binding.get("identifier_column"))
            for row in rows
        ]

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _row_to_fact(
        self,
        row: dict[str, Any],
        ontology_type: str,
        identifier_column: Optional[str],
    ) -> KnowledgeFact:
        """Convert a Neo4j record to a KnowledgeFact.

        Heuristic: if the record contains a single node value, expand its
        properties into the payload. If the record has named columns
        (id/title/summary), use those directly. Falls back to a generic
        repr.
        """
        # Single-node return (`RETURN n`) — flatten properties.
        if len(row) == 1:
            (sole_key, sole_val) = next(iter(row.items()))
            props = _node_to_dict(sole_val)
            if props is not None:
                return self._fact_from_props(props, ontology_type, identifier_column)

        # Tabular return — assume id/title/summary columns are present.
        ent_id = str(
            row.get("id")
            or (row.get(identifier_column) if identifier_column else None)
            or "?"
        )
        title = str(row.get("title") or row.get("name") or ent_id)
        summary = str(row.get("summary") or _short_repr(row))
        return KnowledgeFact(
            ref=KnowledgeRef(
                source=f"neo4j:{self.name}", ontology_type=ontology_type, id=ent_id,
            ),
            payload={"title": title, "summary": summary},
            fetched_by=self.name,
        )

    def _fact_from_props(
        self,
        props: dict[str, Any],
        ontology_type: str,
        identifier_column: Optional[str],
    ) -> KnowledgeFact:
        ent_id = str(
            (props.get(identifier_column) if identifier_column else None)
            or props.get("id")
            or "?"
        )
        title = str(props.get("title") or props.get("name") or ent_id)
        summary = str(props.get("summary") or _short_repr(props))
        return KnowledgeFact(
            ref=KnowledgeRef(
                source=f"neo4j:{self.name}", ontology_type=ontology_type, id=ent_id,
            ),
            payload={"title": title, "summary": summary},
            fetched_by=self.name,
        )

    # -------------------------------------------------------------------------
    # Operator-facing playground hook
    # -------------------------------------------------------------------------
    def run_cypher(
        self, cypher: str, params: dict[str, Any], limit: int = 100
    ) -> dict[str, Any]:
        """Execute arbitrary Cypher with named parameters. Used by the
        Cypher-playground UI. Refuses any write/mutate statement.

        Returns {"columns": [...], "rows": [[...], ...]} or {"error": "..."}.
        """
        CypherSafetyError, assert_read_only = _safety()
        try:
            assert_read_only(cypher, source="cypher_playground")
        except CypherSafetyError as exc:
            return {"error": str(exc)}
        bind = {**(params or {})}
        bind.setdefault("max_results", limit)
        try:
            driver = self._get_driver()
            session_kw = {"database": self._database} if self._database else {}
            with driver.session(**session_kw) as session:
                result = session.run(cypher, **bind)
                records = list(result)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"neo4j: {exc}"}

        if not records:
            return {"columns": [], "rows": []}
        columns = list(records[0].keys())
        rows = []
        for rec in records[:limit]:
            rows.append([_jsonable(rec[c]) for c in columns])
        return {"columns": columns, "rows": rows}

    @staticmethod
    def test_connection(uri: str, user: str, password: str, database: Optional[str] = None):
        """Probe a Neo4j endpoint without registering a source.

        Returns (ok: bool, message: str). Mirrors PostgresResolver.test_connection.
        """
        try:
            from neo4j import GraphDatabase
        except ImportError:
            return False, "neo4j driver not installed"
        try:
            driver = GraphDatabase.driver(uri, auth=((user, password) if user else None))
            try:
                session_kw = {"database": database} if database else {}
                with driver.session(**session_kw) as session:
                    session.run("RETURN 1 AS ok").consume()
            finally:
                driver.close()
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
        return True, "connected"


# =============================================================================
# Helpers (module-level so they're testable)
# =============================================================================
def _node_to_dict(value: Any) -> Optional[dict[str, Any]]:
    """Pull properties off a neo4j Node (or dict-like) value.

    Returns None when `value` isn't a node. The neo4j driver's Node
    type acts like a Mapping; we detect by attribute rather than
    importing the class so tests can pass plain dicts."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    # neo4j.graph.Node has `.items()` and `.labels`
    if hasattr(value, "items") and hasattr(value, "labels"):
        return dict(value.items())
    return None


def _jsonable(v: Any) -> Any:
    """Coerce neo4j types (DateTime, Node, Path, …) into JSON-safe values."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, dict):
        return {k: _jsonable(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    # Node / Relationship / Path / DateTime / etc. — fall back to repr.
    if hasattr(v, "items") and hasattr(v, "labels"):
        return {**{k: _jsonable(val) for k, val in v.items()}, "_labels": list(v.labels)}
    return str(v)


def _short_repr(d: dict[str, Any], max_len: int = 200) -> str:
    parts = []
    for k, v in d.items():
        parts.append(f"{k}={v}")
    return " · ".join(parts)[:max_len]
