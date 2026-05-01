"""Loads YAML scenario definitions from disk into typed dicts.

Mutable at runtime: callers can `register()` new scenarios (e.g. auto-generated
ones from data-source registration) and `unregister()` to remove them. Both
operations persist the YAML file so changes survive a restart.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml


class ScenarioRegistry:
    """In-memory registry of scenarios loaded from `backend/scenarios/*.yaml`."""

    def __init__(self, scenarios: dict[str, dict[str, Any]], directory: Optional[Path] = None):
        self._scenarios = scenarios
        self._directory = directory

    @classmethod
    def from_directory(cls, directory: Path) -> "ScenarioRegistry":
        scenarios: dict[str, dict[str, Any]] = {}
        for path in sorted(directory.glob("*.yaml")):
            with path.open() as fh:
                data = yaml.safe_load(fh)
            if not isinstance(data, dict) or "id" not in data:
                raise RuntimeError(f"Scenario {path} is missing top-level `id`")
            scenarios[data["id"]] = data
        return cls(scenarios, directory=directory)

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

    # -------------------------------------------------------------------------
    # Runtime mutation — used by auto-scenario generation
    # -------------------------------------------------------------------------
    def register(self, scenario: dict[str, Any], *, persist: bool = True) -> None:
        sid = scenario.get("id")
        if not sid:
            raise ValueError("scenario missing 'id'")
        self._scenarios[sid] = scenario
        if persist and self._directory is not None:
            path = self._directory / f"{sid}.yaml"
            path.write_text(yaml.safe_dump(scenario, sort_keys=False))

    def unregister(self, scenario_id: str, *, persist: bool = True) -> None:
        self._scenarios.pop(scenario_id, None)
        if persist and self._directory is not None:
            path = self._directory / f"{scenario_id}.yaml"
            path.unlink(missing_ok=True)
