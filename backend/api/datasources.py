"""Data source management endpoints."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from ..datasources import DataSourceSpec, ResolverError
from ..datasources.postgres_source import PostgresResolver
from ..ontology import inspect_source
from ..state import AppState

router = APIRouter(tags=["datasources"])


# =============================================================================
# Schemas
# =============================================================================
class AddSourceIn(BaseModel):
    """Generic add — used for sqlite/http/postgres/vector_store."""
    id: str
    kind: str  # sqlite | http | postgres | vector_store
    description: str = ""
    config: dict[str, Any] = {}


class TestPostgresIn(BaseModel):
    dsn: str


class TestNeo4jIn(BaseModel):
    uri: str
    user: Optional[str] = None
    password: Optional[str] = None
    database: Optional[str] = None


class RunCypherIn(BaseModel):
    cypher: str
    params: dict[str, Any] = {}
    limit: int = 50


# =============================================================================
# Routes
# =============================================================================
@router.get("/data-sources")
def list_sources(request: Request) -> list[dict]:
    state: AppState = request.app.state.app_state
    out: list[dict] = []
    for spec in state.data_sources.specs():
        out.append(
            {
                "id": spec.id,
                "kind": spec.kind,
                "default": spec.default,
                "description": spec.description,
                "config_summary": _summarise(spec),
            }
        )
    return out


@router.post("/data-sources/upload")
async def upload_csv(
    request: Request,
    file: UploadFile = File(...),
    id: str = Form(...),
    ontology_type: str = Form("Record"),
    id_field: str = Form("id"),
    title_field: str = Form("name"),
    summary_template: str = Form(""),
    description: str = Form(""),
) -> dict:
    """Multipart CSV upload. Saves to backend/data/uploads/{id}.csv and registers."""
    state: AppState = request.app.state.app_state
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="please upload a .csv file")
    project_root = Path(__file__).resolve().parent.parent.parent
    uploads_dir = project_root / "backend" / "data" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    safe_id = id.strip() or f"upload-{uuid.uuid4().hex[:8]}"
    dest = uploads_dir / f"{safe_id}.csv"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    spec = DataSourceSpec(
        id=safe_id,
        kind="csv",
        description=description or f"Uploaded CSV ({file.filename})",
        config={
            "path": str(dest.relative_to(project_root)),
            "ontology_type": ontology_type,
            "id_field": id_field,
            "title_field": title_field,
            "summary_template": summary_template
            or ", ".join(f"{{{c}}}" for c in []),  # empty default; UI can edit later
        },
    )
    try:
        state.data_sources.register(spec)
    except ResolverError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": safe_id}


@router.post("/data-sources")
def add_source(payload: AddSourceIn, request: Request) -> dict:
    state: AppState = request.app.state.app_state
    if payload.kind not in {"sqlite", "http", "postgres", "vector_store", "neo4j"}:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported kind {payload.kind!r}; use the upload endpoint for csv",
        )
    spec = DataSourceSpec(
        id=payload.id,
        kind=payload.kind,
        description=payload.description,
        config=payload.config,
    )
    try:
        state.data_sources.register(spec)
    except (ResolverError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": payload.id}


@router.post("/data-sources/{source_id}/test")
def test_source(source_id: str, request: Request) -> dict:
    state: AppState = request.app.state.app_state
    try:
        sample = state.data_sources.sample(source_id, n=3)
    except ResolverError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "ok": True,
        "sample_facts": [
            {
                "source": f.ref.source,
                "ontology_type": f.ref.ontology_type,
                "id": f.ref.id,
                "title": f.payload.get("title"),
                "summary": f.payload.get("summary"),
                "confidence": f.confidence,
            }
            for f in sample
        ],
    }


@router.get("/data-sources/{source_id}/schema")
def get_source_schema(source_id: str, request: Request) -> dict:
    """Inspect a registered source's schema (table list + columns + sample
    values). Used by the ontology mapping UI."""
    state: AppState = request.app.state.app_state
    spec = state.data_sources._specs.get(source_id)  # type: ignore[attr-defined]
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown source {source_id!r}")
    schema = inspect_source(spec, state.data_sources)
    return schema.model_dump(mode="json")


@router.post("/data-sources/test-postgres")
def test_postgres(payload: TestPostgresIn) -> dict:
    """Probe a Postgres DSN before saving — used by the "Add Postgres" form."""
    ok, message = PostgresResolver.test_connection(payload.dsn)
    return {"ok": ok, "message": message}


@router.post("/data-sources/test-neo4j")
def test_neo4j(payload: TestNeo4jIn) -> dict:
    """Probe a Neo4j endpoint before saving — used by the "Add Neo4j" form."""
    from ..datasources.neo4j_source import Neo4jResolver

    ok, message = Neo4jResolver.test_connection(
        payload.uri, payload.user or "", payload.password or "", payload.database
    )
    return {"ok": ok, "message": message}


@router.post("/data-sources/{source_id}/run-cypher")
def run_cypher(source_id: str, payload: RunCypherIn, request: Request) -> dict:
    """Execute arbitrary Cypher against a Neo4j source — playground.

    Read-only: write/mutate Cypher is rejected before reaching the driver
    by `assert_read_only`. Returns {ok, columns, rows} or {ok=False, error}.
    """
    state: AppState = request.app.state.app_state
    try:
        resolver = state.data_sources.require(source_id)
    except ResolverError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if not hasattr(resolver, "run_cypher"):
        raise HTTPException(
            status_code=400,
            detail=f"source {source_id!r} is not Neo4j (kind doesn't expose Cypher)",
        )
    result = resolver.run_cypher(payload.cypher, payload.params, payload.limit)
    if "error" in result:
        return {"ok": False, "error": result["error"]}
    return {"ok": True, "columns": result["columns"], "rows": result["rows"], "limit": payload.limit}


class RunQueryIn(BaseModel):
    sql: str
    params: dict[str, Any] = {}
    limit: int = 50


@router.post("/data-sources/{source_id}/run-query")
def run_query(source_id: str, payload: RunQueryIn, request: Request) -> dict:
    """Execute arbitrary SQL against a SQLite or Postgres source — playground.

    Returns {ok, columns, rows} or {ok=False, error}. Caps rows at 100.
    """
    state: AppState = request.app.state.app_state
    try:
        resolver = state.data_sources.require(source_id)
    except ResolverError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if not hasattr(resolver, "run_query"):
        raise HTTPException(
            status_code=400,
            detail=f"source kind does not support ad-hoc SQL (only sqlite/postgres do)",
        )
    capped_limit = max(1, min(int(payload.limit or 50), 100))
    result = resolver.run_query(payload.sql, payload.params or {}, capped_limit)  # type: ignore[attr-defined]
    if "error" in result:
        return {"ok": False, "error": result["error"]}
    return {"ok": True, **result, "limit": capped_limit}


@router.delete("/data-sources/{source_id}")
def delete_source(source_id: str, request: Request) -> dict:
    state: AppState = request.app.state.app_state
    try:
        state.data_sources.remove(source_id)
    except ResolverError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": source_id, "removed": True}


# =============================================================================
# Helper
# =============================================================================
def _summarise(spec: DataSourceSpec) -> dict[str, Any]:
    """Return a small payload describing the source — what the UI shows in its row."""
    cfg = spec.config
    if spec.kind == "csv":
        return {"path": cfg.get("path"), "ontology_type": cfg.get("ontology_type")}
    if spec.kind == "sqlite":
        return {"path": cfg.get("path"), "ontology_types": list((cfg.get("queries") or {}).keys())}
    if spec.kind == "http":
        return {"base_url": cfg.get("base_url"), "ontology_types": list((cfg.get("paths") or {}).keys())}
    if spec.kind == "postgres":
        # Don't surface the full DSN
        dsn = cfg.get("dsn", "")
        return {
            "host": dsn.split("@")[-1].split("/")[0] if "@" in dsn else "configured",
            "ontology_types": list((cfg.get("queries") or {}).keys()),
        }
    if spec.kind == "vector_store":
        return {"folder": cfg.get("folder"), "ontology_type": cfg.get("ontology_type")}
    return {}
