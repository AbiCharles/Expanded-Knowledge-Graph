"""Postgres-backed KnowledgeResolver via psycopg3.

Mirrors the SqliteResolver shape — same source spec but with a connection URL.
Use named-parameter binding (`%(name)s` is the psycopg3 form, but we use
`:name` style and translate it to psycopg's `%(name)s` for consistency with
the SQLite spec).

Example source spec:

    id: governance_postgres
    kind: postgres
    dsn: "postgresql://user:pass@localhost:5432/governance"
    queries:
      PriorOverride: |
        SELECT case_id AS id, scenario_id AS title,
               outcome || ' — ' || rationale AS summary
        FROM prior_cases WHERE scenario_id = :scenario_id
        ORDER BY decided_at DESC LIMIT :max_results
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

import psycopg
from tcs_hitl_context import KnowledgeFact, KnowledgeQuery, KnowledgeRef

log = logging.getLogger(__name__)

# Translate `:name` placeholders → psycopg3 `%(name)s` form
_NAMED_PARAM_RE = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")
_FROM_TABLE_RE = re.compile(r"\bFROM\s+([A-Za-z_][\w\.\"`]*)", re.IGNORECASE)


def _to_psycopg_sql(sql: str) -> str:
    return _NAMED_PARAM_RE.sub(r"%(\1)s", sql)


class PostgresResolver:
    def __init__(
        self,
        *,
        source_id: str,
        dsn: str,
        queries: dict[str, str],
        sample_filter: Optional[dict[str, Any]] = None,
    ):
        self.name = source_id
        self._dsn = dsn
        self._queries = {k: _to_psycopg_sql(v) for k, v in queries.items()}
        # Original SQL kept for table extraction during the meta-probe
        self._raw_queries = dict(queries)
        self._sample_filter = sample_filter or {}

    def resolve(self, query: KnowledgeQuery) -> list[KnowledgeFact]:
        sql = self._queries.get(query.ontology_type)
        if sql is None:
            raise ValueError(
                f"PostgresResolver {self.name!r} has no query for ontology_type "
                f"{query.ontology_type!r}; available: {list(self._queries)}"
            )
        params: dict[str, Any] = {**query.filters}
        params.setdefault("max_results", query.max_results)
        try:
            with psycopg.connect(self._dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    cols = [c.name for c in cur.description] if cur.description else []
                    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        except psycopg.Error as exc:
            log.warning("PostgresResolver %s failed: %s", self.name, exc)
            return []
        return [self._row_to_fact(row, query.ontology_type) for row in rows]

    def _row_to_fact(self, row: dict[str, Any], ontology_type: str) -> KnowledgeFact:
        return KnowledgeFact(
            ref=KnowledgeRef(
                source=f"postgres:{self.name}",
                ontology_type=ontology_type,
                id=str(row.get("id", "?")),
            ),
            payload={
                "title": str(row.get("title", "")),
                "summary": str(row.get("summary", "")),
            },
            fetched_by=self.name,
        )

    def sample(self, n: int = 3) -> list[KnowledgeFact]:
        """Probe — same three-tier strategy as SqliteResolver.sample()."""
        if not self._queries:
            return []
        ontology_type = next(iter(self._queries.keys()))
        sql = self._queries[ontology_type]
        raw_sql = self._raw_queries[ontology_type]

        # Tier 1: try the actual query. Bind sample_filter (if any) plus
        # max_results. Falls through if the SQL needs other named params.
        params: dict[str, Any] = {**self._sample_filter}
        params.setdefault("max_results", n)
        try:
            with psycopg.connect(self._dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    cols = [c.name for c in cur.description] if cur.description else []
                    rows = [dict(zip(cols, row)) for row in cur.fetchall()[:n]]
                    if rows:
                        return [self._row_to_fact(r, ontology_type) for r in rows]
        except psycopg.Error as exc:
            log.warning("PostgresResolver %s sample (filter) failed: %s", self.name, exc)

        # Tier 2: meta-probe via SELECT * FROM <table> LIMIT n
        m = _FROM_TABLE_RE.search(raw_sql)
        if m:
            table = m.group(1)
            try:
                with psycopg.connect(self._dsn) as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"SELECT * FROM {table} LIMIT %s", (n,))
                        cols = [c.name for c in cur.description] if cur.description else []
                        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
                        return [self._raw_row_to_fact(r, ontology_type) for r in rows]
            except psycopg.Error as exc:
                log.warning("PostgresResolver %s sample (meta-probe) failed: %s", self.name, exc)
        return []

    def resolve_sql(
        self, *, sql: str, ontology_type: str, params: dict[str, Any], max_results: int = 50
    ) -> list[KnowledgeFact]:
        """Run arbitrary SQL and convert rows to KnowledgeFacts. See SqliteResolver
        for the full rationale."""
        bind: dict[str, Any] = {**(params or {})}
        bind.setdefault("max_results", max_results)
        translated = _to_psycopg_sql(sql)
        try:
            with psycopg.connect(self._dsn, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(translated, bind)
                    cols = [c.name for c in cur.description] if cur.description else []
                    rows = [dict(zip(cols, row)) for row in cur.fetchmany(max_results)]
        except psycopg.Error as exc:
            log.warning("PostgresResolver %s resolve_sql failed: %s", self.name, exc)
            return []
        if rows and all(k in rows[0] for k in ("id", "title", "summary")):
            return [self._row_to_fact(r, ontology_type) for r in rows]
        return [self._raw_row_to_fact(r, ontology_type) for r in rows]

    def run_query(
        self, sql: str, params: dict[str, Any], limit: int = 100
    ) -> dict[str, Any]:
        """Execute arbitrary SQL with `:name` params for the playground UI."""
        sql = (sql or "").strip()
        if not sql:
            return {"error": "empty SQL"}
        if ";" in sql.rstrip(";"):
            return {"error": "multiple statements are not allowed"}
        bind = {**(params or {})}
        bind.setdefault("max_results", limit)
        translated = _to_psycopg_sql(sql)
        try:
            with psycopg.connect(self._dsn, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(translated, bind)
                    cols = [c.name for c in (cur.description or [])]
                    rows = [list(r) for r in cur.fetchmany(limit)]
        except psycopg.Error as exc:
            return {"error": f"postgres: {exc}"}
        return {"columns": cols, "rows": rows}

    def _raw_row_to_fact(self, row: dict[str, Any], ontology_type: str) -> KnowledgeFact:
        keys = list(row.keys())
        first_id = str(row[keys[0]]) if keys else "?"
        title = str(row.get("title") or row.get("name") or row.get(keys[1] if len(keys) > 1 else keys[0], ""))
        summary_parts = [f"{k}={row[k]}" for k in keys[1:5] if row.get(k) is not None]
        summary = " · ".join(summary_parts) or str(row)
        return KnowledgeFact(
            ref=KnowledgeRef(
                source=f"postgres:{self.name}",
                ontology_type=ontology_type,
                id=first_id,
            ),
            payload={"title": title, "summary": summary},
            fetched_by=self.name,
        )

    @staticmethod
    def test_connection(dsn: str) -> tuple[bool, str]:
        try:
            with psycopg.connect(dsn, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            return True, "ok"
        except psycopg.Error as exc:
            return False, str(exc)
