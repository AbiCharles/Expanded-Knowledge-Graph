"""Phase 1 scenario versioning — unit tests for the paths the audit flagged.

Covers:
  - Concurrent register() races (no snapshot is silently overwritten)
  - Crash-window heal-forward (snapshot > live → promote on next boot)
  - Comment + block-scalar preservation through migration
  - Idempotent re-migration
  - unregister() cleans `_versions/<id>/` even when it contains subdirs
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
import yaml

from backend.scenario_loader import ScenarioRegistry


def _make_scenario(sid: str, title: str = "Probe") -> dict[str, Any]:
    return {
        "id": sid,
        "title": title,
        "domain": "Test",
        "autonomous": True,
        "actor_id": "agent-test",
        "operator_role": {"label": "Operator", "name": "tester"},
        "action_type": "data_lookup",
        "action_payload": {},
        "match_keywords": ["probe"],
        "interpreted_as": "test",
        "clarifying_question": "go?",
        "stages": {},
    }


def _seed_scenario(dir_: Path, sid: str, title: str = "Probe") -> ScenarioRegistry:
    """Build a registry with a single scenario already registered at v1."""
    (dir_ / f"{sid}.yaml").write_text(
        yaml.safe_dump(_make_scenario(sid, title), sort_keys=False) + "version: 1\n",
        encoding="utf-8",
    )
    return ScenarioRegistry.from_directory(dir_)


# -----------------------------------------------------------------------------
# Migration — comment preservation
# -----------------------------------------------------------------------------
def test_migration_preserves_comments_and_block_scalars(tmp_path: Path) -> None:
    """Operator-authored YAMLs keep their comments + block scalars when
    the registry boots them for the first time."""
    raw = """# Policy: scenario authored by the procurement team
# Reviewed 2026-Q2
id: SC-TEST-COMMENT
title: Comment-bearing scenario
domain: Test
autonomous: true
actor_id: agent-test
operator_role:
  label: Operator
  name: tester
action_type: data_lookup
action_payload: {}
match_keywords:
- probe
interpreted_as: test
clarifying_question: go?
description: |
  Multi-line
  block scalar
  must survive migration.
stages: {}
"""
    (tmp_path / "SC-TEST-COMMENT.yaml").write_text(raw, encoding="utf-8")

    reg = ScenarioRegistry.from_directory(tmp_path)
    after = (tmp_path / "SC-TEST-COMMENT.yaml").read_text(encoding="utf-8")

    assert "# Policy: scenario authored by the procurement team" in after
    assert "# Reviewed 2026-Q2" in after
    assert "Multi-line\n  block scalar" in after, (
        "block scalar reformatted — yaml.safe_dump leaked into the migration path"
    )
    assert "version: 1" in after

    sc = reg.get("SC-TEST-COMMENT")
    assert sc is not None and sc["version"] == 1

    # Snapshot is byte-identical to the migrated live file
    snap = (tmp_path / "_versions" / "SC-TEST-COMMENT" / "v1.yaml").read_text(encoding="utf-8")
    assert snap == after


def test_migration_is_idempotent(tmp_path: Path) -> None:
    """Booting the registry twice on the same dir is a no-op the second time."""
    _seed_scenario(tmp_path, "SC-TEST-IDEMP")
    live_before = (tmp_path / "SC-TEST-IDEMP.yaml").read_text(encoding="utf-8")
    snap_before = (tmp_path / "_versions" / "SC-TEST-IDEMP" / "v1.yaml").read_text(encoding="utf-8")

    # Reboot.
    reg2 = ScenarioRegistry.from_directory(tmp_path)
    assert reg2.get("SC-TEST-IDEMP")["version"] == 1
    assert reg2.versions_of("SC-TEST-IDEMP") == [1]
    assert (tmp_path / "SC-TEST-IDEMP.yaml").read_text(encoding="utf-8") == live_before
    assert (tmp_path / "_versions" / "SC-TEST-IDEMP" / "v1.yaml").read_text(
        encoding="utf-8"
    ) == snap_before


# -----------------------------------------------------------------------------
# Crash-window heal-forward
# -----------------------------------------------------------------------------
def test_crash_window_orphan_heals_forward(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """If register() wrote vN+1 but crashed before overwriting the live YAML,
    the next boot must promote vN+1 to live so the operator's save isn't lost."""
    sid = "SC-TEST-HEAL"
    _seed_scenario(tmp_path, sid, "v1 title")

    # Forge an orphan v2 snapshot directly (simulates the crash window).
    v2 = _make_scenario(sid, "v2 healed forward")
    v2["version"] = 2
    (tmp_path / "_versions" / sid / "v2.yaml").write_text(
        yaml.safe_dump(v2, sort_keys=False), encoding="utf-8"
    )

    caplog.set_level("WARNING")
    reg = ScenarioRegistry.from_directory(tmp_path)
    sc = reg.get(sid)
    assert sc["version"] == 2
    assert sc["title"] == "v2 healed forward"
    assert any("Healing scenario" in m for m in caplog.messages), (
        "expected a WARNING log line when crash-heal fires"
    )

    # Live YAML on disk now reflects v2.
    live = yaml.safe_load((tmp_path / f"{sid}.yaml").read_text(encoding="utf-8"))
    assert live["title"] == "v2 healed forward"
    assert live["version"] == 2


def test_corrupted_orphan_is_ignored(tmp_path: Path) -> None:
    """A garbled snapshot file must not be promoted to live."""
    sid = "SC-TEST-CORRUPT"
    _seed_scenario(tmp_path, sid, "live v1")
    (tmp_path / "_versions" / sid / "v2.yaml").write_text(
        "::: this is not valid yaml :::", encoding="utf-8"
    )
    reg = ScenarioRegistry.from_directory(tmp_path)
    # Heal should silently skip the corrupted file; live stays at v1.
    sc = reg.get(sid)
    assert sc["version"] == 1
    assert sc["title"] == "live v1"


# -----------------------------------------------------------------------------
# Concurrent register() — no snapshot is silently lost
# -----------------------------------------------------------------------------
def test_concurrent_register_serialises(tmp_path: Path) -> None:
    """N threads register the same scenario at once → N consecutive snapshots
    on disk, no version numbers skipped or duplicated."""
    sid = "SC-TEST-CONCURRENT"
    reg = _seed_scenario(tmp_path, sid)

    N = 12
    errors: list[Exception] = []
    barrier = threading.Barrier(N)

    def worker(i: int) -> None:
        barrier.wait()  # maximise contention at the entry point
        try:
            sc = _make_scenario(sid, title=f"edit {i}")
            reg.register(sc, persist=True)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"register() raised under contention: {errors}"

    # v1 was the seed; v2..v(N+1) are the N concurrent edits.
    versions = reg.versions_of(sid)
    assert versions == list(range(1, N + 2)), (
        f"expected consecutive v1..v{N+1}, got {versions}"
    )

    # Every snapshot is parseable and carries its claimed version.
    for v in versions:
        snap = reg.read_version(sid, v)
        assert snap is not None and snap["version"] == v


# -----------------------------------------------------------------------------
# unregister() — robust against subdirectories
# -----------------------------------------------------------------------------
def test_unregister_handles_subdirs_in_versions_tree(tmp_path: Path) -> None:
    """A stray subdirectory inside `_versions/<id>/` must not 500 unregister()."""
    sid = "SC-TEST-RMTREE"
    reg = _seed_scenario(tmp_path, sid)
    vdir = tmp_path / "_versions" / sid
    (vdir / ".tmp_partial").mkdir()
    (vdir / ".tmp_partial" / "scratch.yaml").write_text("placeholder", encoding="utf-8")

    reg.unregister(sid)

    assert reg.get(sid) is None
    assert not (tmp_path / f"{sid}.yaml").exists()
    assert not vdir.exists(), "_versions tree should be fully removed"


# -----------------------------------------------------------------------------
# read_version / versions_of contract
# -----------------------------------------------------------------------------
def test_read_version_returns_historical_snapshot(tmp_path: Path) -> None:
    sid = "SC-TEST-HIST"
    reg = _seed_scenario(tmp_path, sid, "v1 title")
    reg.register(_make_scenario(sid, "v2 title"), persist=True)
    reg.register(_make_scenario(sid, "v3 title"), persist=True)

    assert reg.versions_of(sid) == [1, 2, 3]
    assert reg.read_version(sid, 1)["title"] == "v1 title"
    assert reg.read_version(sid, 2)["title"] == "v2 title"
    assert reg.read_version(sid, 3)["title"] == "v3 title"
    assert reg.read_version(sid, 99) is None  # unknown version → None, not crash
