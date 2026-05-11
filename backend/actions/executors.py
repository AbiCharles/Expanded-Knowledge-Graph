"""Action executors — what actually runs when a write action is approved.

Two kinds for v1:
  - sql_update: run a parameterised UPDATE/INSERT/DELETE against a
    registered SQLite/Postgres source. SQL is operator-authored at
    registration time (not LLM-generated).
  - http_request: fire an HTTP POST/PUT/PATCH/DELETE against a
    registered HTTP source. Path + body templates support {name}
    substitution from action arguments.

Future: cypher_write (Neo4j writes intentionally bypass cypher_safety
for this code path), service_bus / kafka publish, etc.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

import httpx

from .models import (
    Action,
    ActionExecutionResult,
    HttpRequestExecutor,
    SqlUpdateExecutor,
)

log = logging.getLogger(__name__)


def execute_action(
    action: Action,
    args: dict[str, Any],
    *,
    sources,
) -> ActionExecutionResult:
    """Dispatch on `action.executor.kind` and run the executor.

    `sources` is the `DataSourceRegistry` — needed to resolve the
    target source by id. Any executor failure is caught and surfaced
    as a non-ok ActionExecutionResult so the orchestrator can record it
    on the case without raising further."""
    if isinstance(action.executor, SqlUpdateExecutor):
        return _execute_sql_update(action, args, sources)
    if isinstance(action.executor, HttpRequestExecutor):
        return _execute_http_request(action, args, sources)
    return ActionExecutionResult(
        action_id=action.id,
        ok=False,
        detail=f"unknown executor kind {type(action.executor).__name__!r}",
        args=args,
    )


# =============================================================================
# sql_update
# =============================================================================
def _execute_sql_update(
    action: Action, args: dict[str, Any], sources
) -> ActionExecutionResult:
    executor: SqlUpdateExecutor = action.executor  # type: ignore[assignment]
    spec = sources._specs.get(executor.data_source)  # type: ignore[attr-defined]
    if spec is None:
        return ActionExecutionResult(
            action_id=action.id,
            ok=False,
            detail=f"sql_update target source {executor.data_source!r} not registered",
            args=args,
        )

    try:
        if spec.kind == "sqlite":
            from pathlib import Path

            raw_path = spec.config.get("path", "")
            db_path = Path(raw_path)
            if not db_path.is_absolute():
                db_path = sources._project_root / raw_path  # type: ignore[attr-defined]
            with sqlite3.connect(db_path) as conn:
                cur = conn.execute(executor.sql, args)
                rows = cur.rowcount
                conn.commit()
        elif spec.kind == "postgres":
            import psycopg

            dsn = spec.config["dsn"]
            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    # psycopg uses %(name)s style; rewrite :name placeholders.
                    sql, params_pg = _rewrite_named_to_pyformat(executor.sql, args)
                    cur.execute(sql, params_pg)
                    rows = cur.rowcount
                conn.commit()
        else:
            return ActionExecutionResult(
                action_id=action.id,
                ok=False,
                detail=(
                    f"sql_update can only target sqlite/postgres, "
                    f"not {spec.kind}"
                ),
                args=args,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("action %s sql_update failed: %s", action.id, exc)
        return ActionExecutionResult(
            action_id=action.id,
            ok=False,
            detail=f"sql_update failed: {exc}",
            args=args,
        )

    return ActionExecutionResult(
        action_id=action.id,
        ok=True,
        detail=f"sql_update committed against {executor.data_source}",
        rows_affected=int(rows or 0),
        args=args,
    )


def _rewrite_named_to_pyformat(sql: str, params: dict[str, Any]):
    """Convert SQLAlchemy-ish `:name` to psycopg's `%(name)s` style and
    return (sql_pyformat, params)."""
    import re

    out = re.sub(r":([A-Za-z_]\w*)", r"%(\1)s", sql)
    return out, params


# =============================================================================
# http_request
# =============================================================================
def _execute_http_request(
    action: Action, args: dict[str, Any], sources
) -> ActionExecutionResult:
    executor: HttpRequestExecutor = action.executor  # type: ignore[assignment]
    spec = sources._specs.get(executor.data_source)  # type: ignore[attr-defined]
    if spec is None or spec.kind != "http":
        return ActionExecutionResult(
            action_id=action.id,
            ok=False,
            detail=(
                f"http_request target source {executor.data_source!r} "
                f"not a registered http source"
            ),
            args=args,
        )
    base_url = spec.config["base_url"].rstrip("/")
    headers = {**(spec.config.get("headers") or {})}
    headers.setdefault("content-type", executor.content_type)

    try:
        path = executor.path_template.format(**args)
    except KeyError as exc:
        return ActionExecutionResult(
            action_id=action.id,
            ok=False,
            detail=f"path_template missing argument {exc.args[0]!r}",
            args=args,
        )
    url = base_url + path

    body: Any = None
    if executor.body_template:
        try:
            body_str = executor.body_template.format(**args)
        except KeyError as exc:
            return ActionExecutionResult(
                action_id=action.id,
                ok=False,
                detail=f"body_template missing argument {exc.args[0]!r}",
                args=args,
            )
        if executor.content_type == "application/json":
            try:
                body = json.loads(body_str)
            except json.JSONDecodeError as exc:
                return ActionExecutionResult(
                    action_id=action.id,
                    ok=False,
                    detail=f"body_template did not produce valid JSON: {exc}",
                    args=args,
                )
        else:
            body = body_str

    try:
        with httpx.Client(timeout=10.0) as client:
            kwargs: dict[str, Any] = {"headers": headers}
            if body is not None:
                if isinstance(body, (dict, list)):
                    kwargs["json"] = body
                else:
                    kwargs["content"] = body
            resp = client.request(executor.method, url, **kwargs)
        status = resp.status_code
    except httpx.HTTPError as exc:
        return ActionExecutionResult(
            action_id=action.id,
            ok=False,
            detail=f"http_request failed: {exc}",
            args=args,
        )

    return ActionExecutionResult(
        action_id=action.id,
        ok=200 <= status < 300,
        detail=(
            f"http_request {executor.method} {url} → {status}"
            if 200 <= status < 300
            else f"http_request {executor.method} {url} returned {status}: {resp.text[:200]}"
        ),
        response_status=status,
        args=args,
    )
