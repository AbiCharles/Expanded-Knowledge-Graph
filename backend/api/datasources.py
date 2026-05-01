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
    if payload.kind not in {"sqlite", "http", "postgres", "vector_store"}:
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


@router.post("/data-sources/test-postgres")
def test_postgres(payload: TestPostgresIn) -> dict:
    """Probe a Postgres DSN before saving — used by the "Add Postgres" form."""
    ok, message = PostgresResolver.test_connection(payload.dsn)
    return {"ok": ok, "message": message}


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
