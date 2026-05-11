"""Loads YAML scenario definitions from disk into typed dicts.

Mutable at runtime: callers can `register()` new scenarios (e.g. auto-generated
ones from data-source registration) and `unregister()` to remove them. Both
operations persist the YAML file so changes survive a restart.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import yaml


class ScenarioSchemaError(RuntimeError):
    """Raised when a scenario YAML uses a removed/legacy schema element.

    Phase 3.C hard-removed the per-stage `queries:` block in favour of
    `ontology_queries:`. Any scenario YAML still using `queries:` must be
    migrated; see docs/ontology.md for the recipe.
    """


def _validate_no_legacy_queries(scenario_id: str, data: dict[str, Any]) -> None:
    stages = data.get("stages") or {}
    if not isinstance(stages, dict):
        return
    offending = [
        name
        for name, stage_def in stages.items()
        if isinstance(stage_def, dict) and stage_def.get("queries")
    ]
    if offending:
        raise ScenarioSchemaError(
            f"Scenario {scenario_id!r} uses the removed `queries:` block in "
            f"stage(s) {offending}. Migrate to `ontology_queries:` (see "
            "docs/ontology.md). Each `queries:` entry maps to one "
            "`ontology_queries:` entry by replacing `data_source` + "
            "`ontology_type` + `filter` with `ontology` + `class` + `where`."
        )


class ScenarioRegistry:
    """In-memory registry of scenarios loaded from `backend/scenarios/*.yaml`."""

    def __init__(self, scenarios: dict[str, dict[str, Any]], directory: Optional[Path] = None):
        self._scenarios = scenarios
        self._directory = directory
        # Track per-scenario "freshness" timestamp (unix seconds) — used to
        # sort the operator console chip list newest-first. Loaded from file
        # mtime; updated on register/persist; falls back to current time for
        # in-memory-only entries.
        self._mtimes: dict[str, float] = {}

    @classmethod
    def from_directory(cls, directory: Path) -> "ScenarioRegistry":
        reg = cls({}, directory=directory)
        for path in sorted(directory.glob("*.yaml")):
            with path.open() as fh:
                data = yaml.safe_load(fh)
            if not isinstance(data, dict) or "id" not in data:
                raise RuntimeError(f"Scenario {path} is missing top-level `id`")
            _validate_no_legacy_queries(data["id"], data)
            reg._scenarios[data["id"]] = data
            reg._mtimes[data["id"]] = path.stat().st_mtime
        return reg

    def get(self, scenario_id: str) -> Optional[dict[str, Any]]:
        return self._scenarios.get(scenario_id)

    def require(self, scenario_id: str) -> dict[str, Any]:
        sc = self.get(scenario_id)
        if sc is None:
            raise KeyError(f"Unknown scenario_id: {scenario_id!r}")
        return sc

    def all(self) -> list[dict[str, Any]]:
        return list(self._scenarios.values())

    def ids(self) -> list[str]:
        return list(self._scenarios.keys())

    def mtime_for(self, scenario_id: str) -> Optional[float]:
        """Return unix-seconds 'newness' for the operator-console chip sort.

        For disk-backed scenarios this is the YAML file's mtime; for
        runtime-registered ones (e.g. auto-scenarios in tests where persist=
        False) it's whatever `register()` recorded. Returns None for unknown
        scenarios so callers can decide on a default (the API treats None
        as 0 — sinks to the bottom of newest-first sorts)."""
        return self._mtimes.get(scenario_id)

    # -------------------------------------------------------------------------
    # Runtime mutation — used by auto-scenario generation
    # -------------------------------------------------------------------------
    def register(self, scenario: dict[str, Any], *, persist: bool = True) -> None:
        sid = scenario.get("id")
        if not sid:
            raise ValueError("scenario missing 'id'")
        _validate_no_legacy_queries(sid, scenario)
        self._scenarios[sid] = scenario
        if persist and self._directory is not None:
            path = self._directory / f"{sid}.yaml"
            path.write_text(yaml.safe_dump(scenario, sort_keys=False))
            self._mtimes[sid] = path.stat().st_mtime
        else:
            self._mtimes[sid] = time.time()

    def unregister(self, scenario_id: str, *, persist: bool = True) -> None:
        self._scenarios.pop(scenario_id, None)
        self._mtimes.pop(scenario_id, None)
        if persist and self._directory is not None:
            path = self._directory / f"{scenario_id}.yaml"
            path.unlink(missing_ok=True)
