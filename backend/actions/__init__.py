"""NL→write-action layer: action registry + LLM picker + executors.

See backend/actions/models.py for the data model and
docs/ontology.md (TODO: docs/actions.md) for the design rationale.
"""
from .executors import execute_action
from .loader import ActionError, ActionRegistry, parse_action
from .models import (
    Action,
    ActionArgument,
    ActionExecutionResult,
    HttpRequestExecutor,
    NLActionMatch,
    SqlUpdateExecutor,
)
from .nl_picker import NLActionParseError, parse_nl_action

__all__ = [
    "Action",
    "ActionArgument",
    "ActionError",
    "ActionExecutionResult",
    "ActionRegistry",
    "HttpRequestExecutor",
    "NLActionMatch",
    "NLActionParseError",
    "SqlUpdateExecutor",
    "execute_action",
    "parse_action",
    "parse_nl_action",
]
