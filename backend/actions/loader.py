"""On-disk persistence for action-registry documents.

Mirrors `OntologyRegistry`: actions are YAML files in a directory; the
registry parses them on load, holds them in memory, and exposes the
mutation surface (`register`, `unregister`) that the API drives.

Each YAML file declares ONE action. We keep the file-per-action
convention (rather than a single multi-doc file) so individual actions
can be added/edited/removed without conflict.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional, Union

import yaml
from pydantic import ValidationError

from .models import Action, HttpRequestExecutor, SqlUpdateExecutor

log = logging.getLogger(__name__)


class ActionError(Exception):
    """Raised on parse/validate/lookup failures."""


# =============================================================================
# Format-agnostic parser
# =============================================================================
def _coerce_to_dict(content: Union[str, bytes, dict]) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, bytes):
        content = content.decode("utf-8")
    text = (content or "").strip()
    if not text:
        raise ActionError("empty content")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ActionError(f"could not parse as JSON or YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ActionError("top-level document must be a mapping/object")
    return data


def _build_executor(cfg: dict[str, Any], field_name: str):
    """Manual Union dispatch for one Executor block. Used for both the
    forward `executor` and the optional `compensation` executor."""
    kind = cfg.get("kind")
    if kind == "sql_update":
        return SqlUpdateExecutor.model_validate(cfg)
    if kind == "http_request":
        return HttpRequestExecutor.model_validate(cfg)
    raise ActionError(
        f"unknown {field_name} kind {kind!r} — supported: sql_update, http_request"
    )


def parse_action(content: Union[str, bytes, dict]) -> Action:
    """Parse + validate + dispatch the executor variant.

    Pydantic's discriminated-union support varies by version, so we do
    the dispatch manually based on `{executor,compensation}.kind`."""
    data = _coerce_to_dict(content)
    exec_cfg = data.get("executor")
    if not isinstance(exec_cfg, dict):
        raise ActionError("action requires an `executor:` mapping")
    try:
        data = {**data, "executor": _build_executor(exec_cfg, "executor")}
        # Optional compensation block (for compensatable actions). Same
        # Executor union, same dispatch rules. Validated even when
        # reversibility_class != 'compensatable' so a malformed
        # compensation block fails loudly at registry-load time rather
        # than at the first reviewer click.
        comp_cfg = data.get("compensation")
        if isinstance(comp_cfg, dict):
            data = {**data, "compensation": _build_executor(comp_cfg, "compensation")}
        return Action.model_validate(data)
    except ValidationError as exc:
        raise ActionError(f"invalid action: {exc}") from exc


# =============================================================================
# Registry
# =============================================================================
class ActionRegistry:
    """In-memory action registry, persisted to disk.

    Actions are loaded from `<directory>/*.yaml`. Each file is one
    action. Default-flagged actions refuse deletion via the API."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._actions: dict[str, Action] = {}

    @classmethod
    def from_directory(cls, directory: Path) -> "ActionRegistry":
        reg = cls(directory)
        directory.mkdir(parents=True, exist_ok=True)
        for path in sorted(directory.glob("*.yaml")):
            try:
                with path.open(encoding="utf-8") as fh:
                    action = parse_action(fh.read())
            except ActionError as exc:
                log.warning("skipping malformed action at %s: %s", path, exc)
                continue
            reg._actions[action.id] = action
        return reg

    # ------------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------------
    def get(self, action_id: str) -> Optional[Action]:
        return self._actions.get(action_id)

    def require(self, action_id: str) -> Action:
        a = self.get(action_id)
        if a is None:
            raise ActionError(f"unknown action: {action_id!r}")
        return a

    def all(self) -> list[Action]:
        return list(self._actions.values())

    def ids(self) -> list[str]:
        return list(self._actions.keys())

    # ------------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------------
    def register(self, action: Action) -> None:
        self._actions[action.id] = action
        path = self._directory / f"{action.id}.yaml"
        path.write_text(yaml.safe_dump(action.model_dump(mode="json"), sort_keys=False, allow_unicode=True), encoding="utf-8")

    def unregister(self, action_id: str) -> None:
        existing = self._actions.get(action_id)
        if existing is not None and existing.default:
            raise ActionError(f"refusing to delete default action {action_id!r}")
        self._actions.pop(action_id, None)
        (self._directory / f"{action_id}.yaml").unlink(missing_ok=True)
