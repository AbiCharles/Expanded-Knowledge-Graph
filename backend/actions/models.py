"""Pydantic models for the NL→write-action layer.

An `Action` is a structured operation the agent can take that mutates
state somewhere (a SQL row, an HTTP endpoint, a graph node). Each one
declares its arguments + an executor; the operator's NL prompt → an
LLM picker → a synthesized HITL scenario → reviewer approval →
executor invocation.

Action definitions live as YAML files in `backend/data/actions/`. The
registry mirrors `OntologyRegistry` and `ScenarioRegistry`.
"""
from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Argument schema
# =============================================================================
class ActionArgument(BaseModel):
    """One typed input the action needs to run.

    The LLM picker fills these from the operator's prompt. The reviewer
    sees them rendered before deciding."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: Literal["string", "integer", "decimal", "boolean", "date"] = "string"
    required: bool = True
    description: Optional[str] = None
    # Operators see this as a hint; the LLM uses it to disambiguate
    # extraction from the prompt. e.g. for `sku_id`: "must start with SKU-".
    example: Optional[str] = None


# =============================================================================
# Executor variants — each kind has its own concrete config shape
# =============================================================================
class SqlUpdateExecutor(BaseModel):
    """Run a parameterised SQL UPDATE/INSERT/DELETE against a registered
    SQLite/Postgres source. The SQL is operator-authored at registration
    time (not LLM-generated)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["sql_update"] = "sql_update"
    data_source: str
    sql: str  # uses :name params bound from the action's arguments
    # Optional capture-before-update probe. The executor runs this SELECT
    # against `data_source` BEFORE the main `sql` and merges the returned
    # columns into the action args with each key prefixed by ``before_``.
    # Used by `additional_sql` (history insert) and surfaced on
    # ``ActionExecutionResult.before`` so the diff card has a reliable
    # 'before' snapshot even after server restart.
    before_select_sql: Optional[str] = None
    # Extra statements run AFTER the main `sql`, with the same args dict
    # (now augmented with `before_*` keys + `__case_id`). Typical use is
    # an INSERT into an append-only history table.
    additional_sql: list[str] = Field(default_factory=list)


class HttpRequestExecutor(BaseModel):
    """Fire an HTTP request against a registered HTTP source.

    The request body is rendered by `str.format(**args)` against the
    action's collected arguments."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["http_request"] = "http_request"
    data_source: str
    method: Literal["POST", "PUT", "PATCH", "DELETE"] = "POST"
    path_template: str  # appended to source's base_url; supports {name} substitution
    body_template: Optional[str] = None  # JSON template; {name} substitutions
    content_type: str = "application/json"


Executor = Union[SqlUpdateExecutor, HttpRequestExecutor]


# =============================================================================
# Idempotency — "would this action be a no-op?"
# =============================================================================
class Idempotency(BaseModel):
    """Optional pre-flight check: short-circuit the executor when current
    state already matches what the action would write.

    The orchestrator runs ``predicate_sql`` (a SELECT) against the named
    data_source, binding the action's arguments as ``:name`` params. If the
    query returns ≥1 row, the action is treated as a no-op:

      - the executor is NOT invoked
      - the case still completes successfully but with ``decision_kind=no_op``
      - ``no_op_message`` (a template formatted with the args) is surfaced
        as the closing message

    This catches the "re-tender to the carrier we're already on" case
    cleanly — the planner doesn't see a misleading 'before / after' diff
    showing the same row on both sides.
    """

    model_config = ConfigDict(extra="forbid")

    data_source: str
    predicate_sql: str  # uses :name params bound from the action's arguments
    # Human-friendly message shown in place of the diff card when the action
    # is detected as a no-op. Rendered via str.format(**args) so it can
    # reference the action's arg values (e.g. {new_carrier_id}).
    no_op_message: str = "No change needed — current state already matches the target."
    description: Optional[str] = None


# =============================================================================
# Action + Registry doc
# =============================================================================
class Action(BaseModel):
    """A structured write operation. NL→LLM picker fills `arguments`
    from the operator's prompt; reviewer approves; the executor runs."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: Optional[str] = None
    # HITL is the safe default. Set to false explicitly only for
    # idempotent or pre-approved actions (rare).
    hitl: bool = True
    arguments: list[ActionArgument] = Field(default_factory=list)
    # Discriminator handled at parse time — see ActionRegistry.parse_action.
    executor: Executor
    # Optional pre-flight check that short-circuits execution when the
    # current state already matches the target.
    idempotency: Optional[Idempotency] = None
    # Hints the keyword-fallback picker uses when no LLM is available.
    match_keywords: list[str] = Field(default_factory=list)
    # Built-in actions can't be deleted via the API. Mirrors the same
    # flag on Ontology and DataSourceSpec.
    default: bool = False


class ActionExecutionResult(BaseModel):
    """One attempt to execute an action. Recorded on the case and
    emitted as a lineage event."""

    action_id: str
    ok: bool
    detail: str
    rows_affected: Optional[int] = None
    response_status: Optional[int] = None
    args: dict[str, Any] = Field(default_factory=dict)
    # Pre-mutation snapshot when the executor declared `before_select_sql`.
    # Lets the frontend's before/after diff card render reliably without
    # parsing the bound Booking fact (which may not be available after a
    # server restart). Keys mirror the columns returned by the SELECT.
    before: Optional[dict[str, Any]] = None


