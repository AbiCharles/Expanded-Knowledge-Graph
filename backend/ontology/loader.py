"""On-disk persistence for ontology + mapping documents.

Each ontology lives in two files under `backend/ontologies/`:

  <id>.yaml          — the Ontology document (classes, attributes, relations)
  <id>.mappings.yaml — the Mapping document (per-class source bindings)

Both files round-trip through `parse_*` (accepts YAML or JSON content) and
are persisted as YAML on disk so they remain hand-editable.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional, Union

import yaml
from pydantic import ValidationError

from .models import Mapping, Ontology

log = logging.getLogger(__name__)


class OntologyError(Exception):
    """Raised on parse / validation / lookup failures."""


# =============================================================================
# Format-agnostic parsers
# =============================================================================
def _coerce_to_dict(content: Union[str, bytes, dict]) -> dict[str, Any]:
    """Accept JSON or YAML as text/bytes, or a pre-parsed dict.

    Tries JSON first (it's a strict subset of YAML in most cases but the
    error messages from json are clearer when the input is actually JSON).
    Falls back to YAML on JSONDecodeError.
    """
    if isinstance(content, dict):
        return content
    if isinstance(content, bytes):
        content = content.decode("utf-8")
    text = content.strip()
    if not text:
        raise OntologyError("empty content")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise OntologyError(f"could not parse as JSON or YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise OntologyError("top-level document must be a mapping/object")
    return data


def parse_ontology(content: Union[str, bytes, dict]) -> Ontology:
    data = _coerce_to_dict(content)
    try:
        return Ontology.model_validate(data)
    except ValidationError as exc:
        raise OntologyError(f"invalid ontology: {exc}") from exc


def parse_mapping(content: Union[str, bytes, dict]) -> Mapping:
    data = _coerce_to_dict(content)
    try:
        return Mapping.model_validate(data)
    except ValidationError as exc:
        raise OntologyError(f"invalid mapping: {exc}") from exc


# =============================================================================
# OntologyRegistry
# =============================================================================
class OntologyRegistry:
    """In-memory registry of ontologies + their mappings, persisted to disk.

    Mirrors the shape of `backend/scenario_loader.ScenarioRegistry` so the
    rest of the codebase has one obvious pattern for "things loaded from a
    YAML directory."
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._ontologies: dict[str, Ontology] = {}
        self._mappings: dict[str, Mapping] = {}

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------
    @classmethod
    def from_directory(cls, directory: Path) -> "OntologyRegistry":
        reg = cls(directory)
        directory.mkdir(parents=True, exist_ok=True)
        for path in sorted(directory.glob("*.yaml")):
            if path.name.endswith(".mappings.yaml"):
                continue
            try:
                with path.open(encoding="utf-8") as fh:
                    onto = parse_ontology(fh.read())
            except OntologyError as exc:
                log.warning("skipping malformed ontology at %s: %s", path, exc)
                continue
            reg._ontologies[onto.id] = onto
            mapping_path = directory / f"{onto.id}.mappings.yaml"
            if mapping_path.exists():
                try:
                    with mapping_path.open(encoding="utf-8") as fh:
                        reg._mappings[onto.id] = parse_mapping(fh.read())
                except OntologyError as exc:
                    log.warning(
                        "skipping malformed mapping at %s: %s", mapping_path, exc
                    )
        return reg

    # -------------------------------------------------------------------------
    # Read
    # -------------------------------------------------------------------------
    def get(self, ontology_id: str) -> Optional[Ontology]:
        return self._ontologies.get(ontology_id)

    def require(self, ontology_id: str) -> Ontology:
        onto = self.get(ontology_id)
        if onto is None:
            raise OntologyError(f"unknown ontology: {ontology_id!r}")
        return onto

    def all(self) -> list[Ontology]:
        return list(self._ontologies.values())

    def ids(self) -> list[str]:
        return list(self._ontologies.keys())

    def get_mapping(self, ontology_id: str) -> Optional[Mapping]:
        return self._mappings.get(ontology_id)

    # -------------------------------------------------------------------------
    # Write
    # -------------------------------------------------------------------------
    def register(self, ontology: Ontology) -> None:
        self._ontologies[ontology.id] = ontology
        path = self._directory / f"{ontology.id}.yaml"
        path.write_text(yaml.safe_dump(ontology.model_dump(mode="json"), sort_keys=False, allow_unicode=True), encoding="utf-8")

    def unregister(self, ontology_id: str) -> None:
        existing = self._ontologies.get(ontology_id)
        if existing is not None and existing.default:
            raise OntologyError(
                f"refusing to delete default ontology {ontology_id!r}"
            )
        self._ontologies.pop(ontology_id, None)
        self._mappings.pop(ontology_id, None)
        (self._directory / f"{ontology_id}.yaml").unlink(missing_ok=True)
        (self._directory / f"{ontology_id}.mappings.yaml").unlink(missing_ok=True)

    def save_mapping(self, mapping: Mapping) -> None:
        if mapping.ontology_id not in self._ontologies:
            raise OntologyError(
                f"cannot save mapping for unknown ontology {mapping.ontology_id!r}"
            )
        self._mappings[mapping.ontology_id] = mapping
        path = self._directory / f"{mapping.ontology_id}.mappings.yaml"
        path.write_text(yaml.safe_dump(mapping.model_dump(mode="json"), sort_keys=False, allow_unicode=True), encoding="utf-8")
