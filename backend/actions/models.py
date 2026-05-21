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


