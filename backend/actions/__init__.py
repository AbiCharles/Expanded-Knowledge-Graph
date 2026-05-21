"""Write-action layer: action registry + executors.

See backend/actions/models.py for the data model. Actions are referenced
by hand-authored scenarios via an `_executor` block; the orchestrator
invokes the matching executor when the reviewer approves.
"""
from .executors import execute_action
from .loader import ActionError, ActionRegistry, parse_action
from .models import (
    Action,
    ActionArgument,
    ActionExecutionResult,
    HttpRequestExecutor,
    SqlUpdateExecutor,
)

__all__ = [
    "Action",
    "ActionArgument",
    "ActionError",
    "ActionExecutionResult",
    "ActionRegistry",
    "HttpRequestExecutor",
    "SqlUpdateExecutor",
    "execute_action",
    "parse_action",
]
