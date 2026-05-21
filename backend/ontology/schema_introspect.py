"""Per-resolver schema introspection — used by the LLM mapper to know what
columns each registered data source exposes.

Returns a uniform `SourceSchema` regardless of connector kind. Connectors
that can't expose a schema (HTTP, vector store) return an empty
`tables: []` plus a `note` explaining why; the mapper treats those as
"don't suggest mappings here, but the caller can still wire up bindings
by hand."
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..datasources import DataSourceRegistry, DataSourceSpec

log = logging.getLogger(__name__)


# =============================================================================
# Models
# =============================================================================
class ColumnInfo(BaseModel):
    name: str
    type: str = "unknown"
    nullable: Optional[bool] = None
    sample_values: list[Any] = Field(default_factory=list)


class TableInfo(BaseModel):
    name: str
    columns: list[ColumnInfo] = Field(default_factory=list)
    sample_row_count: int = 0


class SourceSchema(BaseModel):
    source_id: str
    kind: str
    tables: list[TableInfo] = Field(default_factory=list)
    note: Optional[str] = None  # set when no real schema is available


# =============================================================================
# Public entry point
# =============================================================================
def inspect_source(
    spec: DataSourceSpec, registry: DataSourceRegistry, *, sample_n: int = 3
) -> SourceSchema:
    """Dispatch on `spec.kind` to the right introspection helper."""
    project_root = registry._project_root  # type: ignore[attr-defined]
    if spec.kind == "csv":
        return _inspect_csv(spec, project_root, sample_n=sample_n)
    if spec.kind == "sqlite":
        return _inspect_sqlite(spec, project_root, sample_n=sample_n)
    if spec.kind == "postgres":
        return _inspect_postgres(spec, sample_n=sample_n)
    if spec.kind == "neo4j":
        return _inspect_neo4j(spec, sample_n=sample_n)
    if spec.kind == "http":
        return SourceSchema(
            source_id=spec.id, kind=spec.kind, tables=[],
            note=(
                "HTTP source — no schema introspection. "
                f"Available ontology_types: {list(spec.config.get('paths', {}).keys())}"
            ),
        )
    if spec.kind == "vector_store":
        return SourceSchema(
            source_id=spec.id, kind=spec.kind, tables=[],
            note=(
                "Vector store — no tabular schema. Single ontology_type: "
                f"{spec.config.get('ontology_type', 'PolicyExcerpt')}"
            ),
        )
    return SourceSchema(
        source_id=spec.id, kind=spec.kind, tables=[],
        note=f"unknown kind {spec.kind!r} — no introspection",
    )


# =============================================================================
# CSV
# =============================================================================
def _inspect_csv(
    spec: DataSourceSpec, project_root: Path, *, sample_n: int
) -> SourceSchema:
    raw_path = spec.config.get("path")
    if not raw_path:
        return SourceSchema(source_id=spec.id, kind=spec.kind, note="no path in spec")
    path = Path(raw_path)
    if not path.is_absolute():
        path = project_root / raw_path
    if not path.exists():
        return SourceSchema(
            source_id=spec.id, kind=spec.kind,
            note=f"csv file not found: {path}",
        )
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        sample_rows = []
        for i, row in enumerate(reader):
            if i >= sample_n:
                break
            sample_rows.append(row)
    columns = []
    for col in fieldnames:
        sample_values = [row.get(col) for row in sample_rows if row.get(col) not in (None, "")]
        columns.append(
            ColumnInfo(
                name=col,
                type=_guess_type_from_values(sample_values),
                sample_values=sample_values[:sample_n],
            )
        )
    table = TableInfo(
        name=path.stem,
        columns=columns,
        sample_row_count=len(sample_rows),
    )
    return SourceSchema(source_id=spec.id, kind=spec.kind, tables=[table])


# =============================================================================
# SQLite
# =============================================================================
def _inspect_sqlite(
    spec: DataSourceSpec, project_root: Path, *, sample_n: int
) -> SourceSchema:
    import sqlite3

    raw_path = spec.config.get("path")
    if not raw_path:
        return SourceSchema(source_id=spec.id, kind=spec.kind, note="no path in spec")
    path = Path(raw_path)
    if not path.is_absolute():
        path = project_root / raw_path
    if not path.exists():
        return SourceSchema(
            source_id=spec.id, kind=spec.kind,
            note=f"sqlite file not found: {path}",
        )
    tables: list[TableInfo] = []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        names = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        for table_name in names:
            try:
                cols_meta = list(
                    conn.execute(f'PRAGMA table_info("{table_name}")')
                )
                sample_rows = [
                    dict(r)
                    for r in conn.execute(
                        f'SELECT * FROM "{table_name}" LIMIT {sample_n}'
                    )
                ]
            except sqlite3.Error as exc:
                log.warning("sqlite introspect %s/%s failed: %s", spec.id, table_name, exc)
                continue
            columns = []
            for c in cols_meta:
                col_name = c["name"]
                vals = [row.get(col_name) for row in sample_rows if row.get(col_name) is not None]
                columns.append(
                    ColumnInfo(
                        name=col_name,
                        type=(c["type"] or "unknown").lower(),
                        nullable=not bool(c["notnull"]),
                        sample_values=vals[:sample_n],
                    )
                )
            tables.append(
                TableInfo(name=table_name, columns=columns, sample_row_count=len(sample_rows))
            )
    return SourceSchema(source_id=spec.id, kind=spec.kind, tables=tables)


# =============================================================================
# Postgres
# =============================================================================
def _inspect_postgres(spec: DataSourceSpec, *, sample_n: int) -> SourceSchema:
    try:
        import psycopg
    except ImportError:
        return SourceSchema(
            source_id=spec.id, kind=spec.kind, note="psycopg not installed",
        )
    dsn = spec.config.get("dsn")
    if not dsn:
        return SourceSchema(source_id=spec.id, kind=spec.kind, note="no dsn in spec")
    tables: list[TableInfo] = []
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_schema, table_name "
                    "FROM information_schema.tables "
                    "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                    "ORDER BY table_schema, table_name LIMIT 100"
                )
                table_rows = cur.fetchall()
            for schema_name, table_name in table_rows:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT column_name, data_type, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_schema = %s AND table_name = %s "
                        "ORDER BY ordinal_position",
                        (schema_name, table_name),
                    )
                    col_rows = cur.fetchall()
                with conn.cursor() as cur:
                    qualified = f'"{schema_name}"."{table_name}"'
                    try:
                        cur.execute(f"SELECT * FROM {qualified} LIMIT {sample_n}")
                        cols = [d.name for d in (cur.description or [])]
                        sample_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "pg sample %s.%s failed: %s", schema_name, table_name, exc
                        )
                        sample_rows = []
                columns = []
                for col_name, data_type, is_nullable in col_rows:
                    vals = [
                        row.get(col_name) for row in sample_rows if row.get(col_name) is not None
                    ]
                    columns.append(
                        ColumnInfo(
                            name=col_name,
                            type=str(data_type),
                            nullable=(is_nullable == "YES"),
                            sample_values=[_jsonable(v) for v in vals[:sample_n]],
                        )
                    )
                qualified_name = (
                    table_name if schema_name == "public" else f"{schema_name}.{table_name}"
                )
                tables.append(
                    TableInfo(
                        name=qualified_name,
                        columns=columns,
                        sample_row_count=len(sample_rows),
                    )
                )
    except Exception as exc:  # noqa: BLE001
        return SourceSchema(
            source_id=spec.id, kind=spec.kind, tables=tables,
            note=f"connection or introspection failed: {exc}",
        )
    return SourceSchema(source_id=spec.id, kind=spec.kind, tables=tables)


# =============================================================================
# Neo4j
# =============================================================================
def _inspect_neo4j(spec: DataSourceSpec, *, sample_n: int) -> SourceSchema:
    """Treat each Neo4j label as a 'table' and each property as a 'column'.

    Sample-value collection per (label, property) is what powers the
    schema-aware NL parser hint — *"country: string (samples: NL, DE,
    FR)"* lets the LLM extract `country: NL` from a prompt like
    "Dutch suppliers" instead of taking the human-readable form.
    """
    try:
        from neo4j import GraphDatabase  # type: ignore[import-not-found]
    except ImportError:
        return SourceSchema(
            source_id=spec.id, kind=spec.kind, note="neo4j driver not installed",
        )
    uri = spec.config.get("uri")
    if not uri:
        return SourceSchema(source_id=spec.id, kind=spec.kind, note="no uri in spec")

    user = spec.config.get("user")
    password = spec.config.get("password")
    database = spec.config.get("database")

    tables: list[TableInfo] = []
    auth = (user, password) if user else None
    try:
        driver = GraphDatabase.driver(uri, auth=auth)
    except Exception as exc:  # noqa: BLE001
        return SourceSchema(
            source_id=spec.id, kind=spec.kind, note=f"could not open driver: {exc}",
        )
    try:
        session_kw = {"database": database} if database else {}
        with driver.session(**session_kw) as session:
            try:
                labels = [
                    rec["label"]
                    for rec in session.run("CALL db.labels() YIELD label RETURN label")
                ]
            except Exception as exc:  # noqa: BLE001
                return SourceSchema(
                    source_id=spec.id, kind=spec.kind, tables=[],
                    note=f"db.labels() failed: {exc}",
                )

            for label in labels[:50]:  # cap so we don't enumerate huge taxonomies
                # Pull a small sample of nodes for this label so we can
                # collect property names + per-property sample values.
                try:
                    rows = list(
                        session.run(
                            f"MATCH (n:`{label}`) RETURN n LIMIT $n",
                            n=max(10, sample_n * 5),
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "neo4j inspect %s/%s sample failed: %s",
                        spec.id, label, exc,
                    )
                    continue

                property_samples: dict[str, list[Any]] = {}
                for rec in rows:
                    node = rec["n"]
                    items = node.items() if hasattr(node, "items") else (
                        list(node.items()) if isinstance(node, dict) else []
                    )
                    for k, v in items:
                        if v is None:
                            continue
                        bucket = property_samples.setdefault(k, [])
                        if v not in bucket:
                            bucket.append(v)
                columns = [
                    ColumnInfo(
                        name=k,
                        type=_neo4j_type_for(v_list[0]) if v_list else "unknown",
                        sample_values=[_jsonable(v) for v in v_list[:sample_n]],
                    )
                    for k, v_list in sorted(property_samples.items())
                ]
                tables.append(
                    TableInfo(
                        name=label, columns=columns, sample_row_count=len(rows),
                    )
                )
    finally:
        try:
            driver.close()
        except Exception:  # noqa: BLE001
            pass
    return SourceSchema(source_id=spec.id, kind=spec.kind, tables=tables)


def _neo4j_type_for(v: Any) -> str:
    """Cheap type hint for Neo4j property samples — neo4j.time types repr
    as e.g. `Date(2026-04-12)`, ints and floats are obvious."""
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "decimal"
    if hasattr(v, "year") and hasattr(v, "month"):
        return "date"
    return "string"


# =============================================================================
# Helpers
# =============================================================================
def _guess_type_from_values(values: list[Any]) -> str:
    if not values:
        return "unknown"
    looks_int = all(_is_intish(v) for v in values)
    if looks_int:
        return "integer"
    looks_decimal = all(_is_floatish(v) for v in values)
    if looks_decimal:
        return "decimal"
    return "string"


def _is_intish(v: Any) -> bool:
    try:
        int(str(v))
        return "." not in str(v)
    except (TypeError, ValueError):
        return False


def _is_floatish(v: Any) -> bool:
    try:
        float(str(v))
        return True
    except (TypeError, ValueError):
        return False


def _jsonable(v: Any) -> Any:
    """Coerce types Postgres returns (datetime, Decimal) to JSON-friendly values."""
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)
