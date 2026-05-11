"""SQLite-backed KnowledgeResolver.

The source spec declares one or more named SQL queries keyed by ontology_type.
Each query uses named-parameter binding (`:name`) and is matched against the
incoming KnowledgeQuery's `filters`.

Example source spec:

    id: governance_sqlite
    kind: sqlite
    path: backend/data/governance.sqlite
    queries:
      PriorOverride: |
        SELECT case_id AS id, scenario_id AS title,
               outcome || ' — ' || rationale AS summary
        FROM prior_cases WHERE scenario_id = :scenario_id
        ORDER BY decided_at DESC LIMIT :max_results
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

from tcs_hitl_context import KnowledgeFact, KnowledgeQuery, KnowledgeRef

# Pull "<table>" out of "... FROM <table> ..." (case-insensitive). Greedy enough
# to grab `schema.table` or quoted identifiers; intentionally *not* a SQL parser.
_FROM_TABLE_RE = re.compile(r"\bFROM\s+([A-Za-z_][\w\.\"`]*)", re.IGNORECASE)


class SqliteResolver:
    def __init__(
        self,
        *,
        source_id: str,
        path: Path,
        queries: dict[str, str],
        sample_filter: Optional[dict[str, Any]] = None,
    ):
        self.name = source_id
        self._path = path
        self._queries = queries
        # Default values used by `sample()` so the Test button works against
        # parameterised queries. Spec authors set these to known-good filter
        # values (e.g. `{ scenario_id: SC-TC-007 }`).
        self._sample_filter = sample_filter or {}

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def resolve(self, query: KnowledgeQuery) -> list[KnowledgeFact]:
        # Binding-driven (Phase 3.C) takes precedence: the OntologyResolver
        # injects __binding__ with `query_template` (preferred), `table`
        # (auto-`SELECT *` derived), and `identifier_column`.
        binding = query.filters.get("__binding__") or {}
        sql = binding.get("query_template")
        if not sql and binding.get("table"):
            id_col = binding.get("identifier_column") or "id"
            sql = (
                f'SELECT * FROM "{binding["table"]}" '
                f'WHERE "{id_col}" = :{id_col} '
                f"LIMIT :max_results"
            )
        # Fallback to the source-spec `queries:` dict for sources that
        # haven't been migrated to mapping-driven config yet.
        if not sql:
            sql = self._queries.get(query.ontology_type)
        if sql is None:
            raise ValueError(
                f"SqliteResolver {self.name!r} has no query for ontology_type "
                f"{query.ontology_type!r}; available: {list(self._queries)} "
                "and no binding.query_template/table provided"
            )
        # Pull off framework-private keys before binding to SQL params.
        params: dict[str, Any] = {
            k: v
            for k, v in query.filters.items()
            if k not in ("__binding__", "__ontology__")
        }
        params.setdefault("max_results", query.max_results)
        with self._connect() as conn:
            cursor = conn.execute(sql, params)
            rows = [dict(r) for r in cursor.fetchall()]
        return [self._row_to_fact(row, query.ontology_type) for row in rows]

    def _row_to_fact(self, row: dict[str, Any], ontology_type: str) -> KnowledgeFact:
        ref = KnowledgeRef(
            source=f"sqlite:{self.name}",
            ontology_type=ontology_type,
            id=str(row.get("id", "?")),
        )
        return KnowledgeFact(
            ref=ref,
            payload={
                "title": str(row.get("title", "")),
                "summary": str(row.get("summary", "")),
            },
            fetched_by=self.name,
        )

    def sample(self, n: int = 3) -> list[KnowledgeFact]:
        """Probe — used by the Test button.

        Three-tier strategy:
          1. If the source spec declared `sample_filter`, run the actual query
             with those filter values. Highest fidelity.
          2. Otherwise, try a meta-probe: `SELECT * FROM <table> LIMIT n` against
             the table parsed out of the first query. Doesn't need filter values.
          3. Otherwise return [].
        """
        if not self._queries:
            return []
        ontology_type, sql = next(iter(self._queries.items()))

        # Tier 1: try the actual query. Bind sample_filter (if any) plus
        # max_results. If the SQL needs other named params we don't have,
        # SQLite raises and we fall through to Tier 2.
        params: dict[str, Any] = {**self._sample_filter}
        params.setdefault("max_results", n)
        with self._connect() as conn:
            try:
                cursor = conn.execute(sql, params)
                rows = [dict(r) for r in cursor.fetchall()[:n]]
                if rows:
                    return [self._row_to_fact(r, ontology_type) for r in rows]
            except sqlite3.Error:
                pass

        # Tier 2: meta-probe via SELECT * FROM <table> LIMIT n
        m = _FROM_TABLE_RE.search(sql)
        if m:
            table = m.group(1)
            with self._connect() as conn:
                try:
                    cursor = conn.execute(f"SELECT * FROM {table} LIMIT ?", (n,))
                    raw = [dict(r) for r in cursor.fetchall()]
                    return [self._raw_row_to_fact(r, ontology_type) for r in raw]
                except sqlite3.Error:
                    pass
        return []

    def resolve_sql(
        self, *, sql: str, ontology_type: str, params: dict[str, Any], max_results: int = 50
    ) -> list[KnowledgeFact]:
        """Run arbitrary SQL and convert rows to KnowledgeFacts.

        Used by binders when a scenario has a `sql_override` on its query block
        — i.e. the operator saved a one-off query as a scenario via the
        playground rather than via a sources.yaml query entry.
        """
        bind: dict[str, Any] = {**(params or {})}
        bind.setdefault("max_results", max_results)
        try:
            with self._connect() as conn:
                cursor = conn.execute(sql, bind)
                rows = [dict(r) for r in cursor.fetchmany(max_results)]
        except sqlite3.Error:
            return []
        # Prefer id/title/summary aliases (same convention as the registered
        # query path); fall back to raw-row formatting if those are missing.
        if rows and all(k in rows[0] for k in ("id", "title", "summary")):
            return [self._row_to_fact(r, ontology_type) for r in rows]
        return [self._raw_row_to_fact(r, ontology_type) for r in rows]

    def run_query(
        self, sql: str, params: dict[str, Any], limit: int = 100
    ) -> dict[str, Any]:
        """Execute arbitrary SQL with named params for the playground UI.

        Returns {"columns": [...], "rows": [[...], ...]} or {"error": "..."}.
        Refuses multi-statement input. Caps rows at `limit`.
        """
        sql = (sql or "").strip()
        if not sql:
            return {"error": "empty SQL"}
        if ";" in sql.rstrip(";"):
            return {"error": "multiple statements are not allowed"}
        bind = {**(params or {})}
        bind.setdefault("max_results", limit)
        try:
            with self._connect() as conn:
                cursor = conn.execute(sql, bind)
                cols = [d[0] for d in (cursor.description or [])]
                rows = [list(r) for r in cursor.fetchmany(limit)]
        except sqlite3.Error as exc:
            return {"error": f"sqlite: {exc}"}
        return {"columns": cols, "rows": rows}

    def _raw_row_to_fact(self, row: dict[str, Any], ontology_type: str) -> KnowledgeFact:
        """Convert a `SELECT *` row to a fact when we don't have id/title/summary aliases.

        Picks the first column as id, the second as title (or the row's text repr
        as fallback), and the rest as a key=value summary.
        """
        keys = list(row.keys())
        first_id = str(row[keys[0]]) if keys else "?"
        title = str(row.get("title") or row.get("name") or row.get(keys[1] if len(keys) > 1 else keys[0], ""))
        summary_parts = [f"{k}={row[k]}" for k in keys[1:5] if row.get(k) is not None]
        summary = " · ".join(summary_parts) or str(row)
        return KnowledgeFact(
            ref=KnowledgeRef(
                source=f"sqlite:{self.name}",
                ontology_type=ontology_type,
                id=first_id,
            ),
            payload={"title": title, "summary": summary},
            fetched_by=self.name,
        )
