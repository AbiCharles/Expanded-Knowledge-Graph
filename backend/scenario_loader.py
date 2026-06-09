"""Loads YAML scenario definitions from disk into typed dicts.

Mutable at runtime: callers can `register()` new scenarios (e.g. auto-generated
ones from data-source registration) and `unregister()` to remove them. Both
operations persist the YAML file so changes survive a restart.

Versioning (Phase 1 of the "compounding" roadmap):
  - Each scenario carries a top-level `version: int` field.
  - On every `register()` (i.e. every edit), the prior content is snapshotted
    as an immutable `_versions/<id>/v<N>.yaml` BEFORE the live file is
    rewritten with `version: N+1`.
  - First-boot migration seeds `v1` for any scenario without versioning
    metadata; idempotent on subsequent boots.
  - `read_version()` / `versions_of()` expose the snapshots to API + UI so
    cases can render the exact scenario state they ran against.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Optional

import yaml


# Sub-directory under the scenarios dir holding immutable per-version
# snapshots. Leading underscore keeps it out of `glob("*.yaml")` scans.
VERSIONS_DIRNAME = "_versions"
_VERSION_FILE_RE = re.compile(r"^v(\d+)\.yaml$")


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
            "`ontology_type` + `filter` with `ontology` + `class` + `version`."
        )


def _dump_scenario(scenario: dict[str, Any]) -> str:
    return yaml.safe_dump(scenario, sort_keys=False, allow_unicode=True)


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

    # -------------------------------------------------------------------------
    # Loading + migration
    # -------------------------------------------------------------------------
    @classmethod
    def from_directory(cls, directory: Path) -> "ScenarioRegistry":
        reg = cls({}, directory=directory)
        for path in sorted(directory.glob("*.yaml")):
            with path.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if not isinstance(data, dict) or "id" not in data:
                raise RuntimeError(f"Scenario {path} is missing top-level `id`")
            _validate_no_legacy_queries(data["id"], data)
            # Backward-compat migration: stamp `version: 1` + drop a
            # `_versions/<id>/v1.yaml` snapshot for anything that doesn't
            # have versioning yet. Idempotent: a scenario that already
            # carries `version: N` and has the matching snapshot is left
            # alone; only the missing snapshot file (if any) is healed.
            reg._migrate_to_versioned(path, data)
            reg._scenarios[data["id"]] = data
            reg._mtimes[data["id"]] = path.stat().st_mtime
        return reg

    def _migrate_to_versioned(self, live_path: Path, data: dict[str, Any]) -> None:
        """Seed a v1 snapshot for un-versioned scenarios (idempotent).

        Mutates `data` to add `version: 1` when missing and rewrites the
        live YAML so the field sticks.
        """
        if self._directory is None:
            return
        sid = data["id"]
        existing = data.get("version")
        if not isinstance(existing, int) or existing < 1:
            data["version"] = 1
            existing = 1
            # Re-serialise the live YAML so the field is persisted.
            live_path.write_text(_dump_scenario(data), encoding="utf-8")
        # Ensure the matching snapshot file exists.
        snapshot = self._version_path(sid, existing)
        if not snapshot.exists():
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text(_dump_scenario(data), encoding="utf-8")

    # -------------------------------------------------------------------------
    # Read API
    # -------------------------------------------------------------------------
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
    # Versioning
    # -------------------------------------------------------------------------
    def versions_dir(self, scenario_id: str) -> Optional[Path]:
        if self._directory is None:
            return None
        return self._directory / VERSIONS_DIRNAME / scenario_id

    def _version_path(self, scenario_id: str, version: int) -> Path:
        assert self._directory is not None
        return self._directory / VERSIONS_DIRNAME / scenario_id / f"v{version}.yaml"

    def versions_of(self, scenario_id: str) -> list[int]:
        """All version numbers that have an on-disk snapshot, ascending.

        Returns [] for in-memory-only scenarios (no directory backing) or
        when no snapshots exist yet.
        """
        vdir = self.versions_dir(scenario_id)
        if vdir is None or not vdir.is_dir():
            return []
        versions: list[int] = []
        for p in vdir.iterdir():
            m = _VERSION_FILE_RE.match(p.name)
            if m:
                versions.append(int(m.group(1)))
        versions.sort()
        return versions

    def read_version(self, scenario_id: str, version: int) -> Optional[dict[str, Any]]:
        """Return the parsed dict for a specific historical version, or None.

        No caching — Case-spec opens are infrequent and the files are small.
        Returns None when the directory isn't backed or the snapshot is
        missing (deleted scenario, version never persisted).
        """
        vpath = (
            self._version_path(scenario_id, version)
            if self._directory is not None
            else None
        )
        if vpath is None or not vpath.exists():
            return None
        with vpath.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            return None
        return data

    def saved_at_for_version(self, scenario_id: str, version: int) -> Optional[float]:
        """Unix-seconds mtime of the snapshot file for `version` (or None)."""
        if self._directory is None:
            return None
        vpath = self._version_path(scenario_id, version)
        if not vpath.exists():
            return None
        return vpath.stat().st_mtime

    # -------------------------------------------------------------------------
    # Runtime mutation
    # -------------------------------------------------------------------------
    def register(self, scenario: dict[str, Any], *, persist: bool = True) -> None:
        """Register / update a scenario.

        On every persisted edit, the new state is bumped to `version: N+1`
        and snapshotted under `_versions/<id>/v<N+1>.yaml` BEFORE the live
        file is overwritten. The version field is also stamped on the
        in-memory copy so callers (e.g. cases pinning their version) see it.
        """
        sid = scenario.get("id")
        if not sid:
            raise ValueError("scenario missing 'id'")
        _validate_no_legacy_queries(sid, scenario)

        if persist and self._directory is not None:
            # Bump to next version (current live + 1 if known, else
            # max-on-disk + 1). Either way the resulting number is
            # strictly greater than any existing snapshot for this id.
            current = (self._scenarios.get(sid) or {}).get("version")
            current = current if isinstance(current, int) else 0
            on_disk = max(self.versions_of(sid) or [0])
            next_version = max(current, on_disk) + 1
            scenario["version"] = next_version

            # Snapshot first (immutable), then overwrite the live file.
            snapshot = self._version_path(sid, next_version)
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            payload = _dump_scenario(scenario)
            snapshot.write_text(payload, encoding="utf-8")
            live = self._directory / f"{sid}.yaml"
            live.write_text(payload, encoding="utf-8")
            self._mtimes[sid] = live.stat().st_mtime
        else:
            # Ephemeral / no directory backing — keep an in-memory
            # `version` so consumers don't have to special-case None.
            scenario.setdefault("version", 1)
            self._mtimes[sid] = time.time()

        self._scenarios[sid] = scenario

    def unregister(self, scenario_id: str, *, persist: bool = True) -> None:
        self._scenarios.pop(scenario_id, None)
        self._mtimes.pop(scenario_id, None)
        if persist and self._directory is not None:
            (self._directory / f"{scenario_id}.yaml").unlink(missing_ok=True)
            vdir = self.versions_dir(scenario_id)
            if vdir and vdir.is_dir():
                for f in vdir.iterdir():
                    f.unlink()
                vdir.rmdir()
