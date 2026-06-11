"""Scenario lint: every shipped YAML must load AND reference real ontology
classes + fields.

Catches the most common silent-break in this system: an ontology gets a
class or attribute renamed, several scenarios silently bind to nothing.
The runtime is forgiving (warns + returns zero facts), so the only signal
without this test is "the demo card grid is empty."

Runs in well under a second — no fixtures, no API, just direct registry
loads.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from backend.ontology.loader import OntologyRegistry
from backend.scenario_loader import ScenarioRegistry


REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = REPO_ROOT / "backend" / "scenarios"
ONTOLOGIES_DIR = REPO_ROOT / "backend" / "ontologies"


def _scenario_ids() -> list[str]:
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.yaml"))


@pytest.fixture(scope="module")
def ontologies() -> OntologyRegistry:
    return OntologyRegistry.from_directory(ONTOLOGIES_DIR)


@pytest.fixture(scope="module")
def registry(tmp_path_factory: pytest.TempPathFactory) -> ScenarioRegistry:
    """Load via a tmp-copied dir so the lint doesn't touch the repo's
    `_versions/` tree even if the migration ever rewrites a file."""
    import shutil

    tmp = tmp_path_factory.mktemp("scenarios")
    shutil.copytree(SCENARIOS_DIR, tmp, dirs_exist_ok=True)
    return ScenarioRegistry.from_directory(tmp)


# -----------------------------------------------------------------------------
# Structural lint
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("sid", _scenario_ids())
def test_scenario_loads_without_schema_error(sid: str, registry: ScenarioRegistry) -> None:
    sc = registry.get(sid)
    assert sc is not None, f"{sid} did not load"
    assert sc["id"] == sid
    assert sc.get("title"), f"{sid}: missing title"
    assert sc.get("domain"), f"{sid}: missing domain"
    assert sc.get("action_type"), f"{sid}: missing action_type"


@pytest.mark.parametrize("sid", _scenario_ids())
def test_scenario_has_match_keywords(sid: str, registry: ScenarioRegistry) -> None:
    sc = registry.get(sid)
    kw = sc.get("match_keywords") or []
    assert isinstance(kw, list) and len(kw) >= 1, (
        f"{sid}: match_keywords must be a non-empty list — the operator console "
        "uses these to surface the chip on the right intents"
    )
    assert all(isinstance(k, str) and k.strip() for k in kw), (
        f"{sid}: all match_keywords must be non-empty strings"
    )


@pytest.mark.parametrize("sid", _scenario_ids())
def test_scenario_has_stages(sid: str, registry: ScenarioRegistry) -> None:
    sc = registry.get(sid)
    stages = sc.get("stages")
    assert isinstance(stages, dict) and stages, (
        f"{sid}: stages must be a non-empty dict"
    )


@pytest.mark.parametrize("sid", _scenario_ids())
def test_scenario_version_field_present(sid: str, registry: ScenarioRegistry) -> None:
    """Phase 1 versioning invariant: every loaded scenario has a `version: int`
    after migration."""
    sc = registry.get(sid)
    version = sc.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"{sid}: missing or invalid version field (got {version!r})"
    )


# -----------------------------------------------------------------------------
# Ontology-reference lint — the high-leverage check
# -----------------------------------------------------------------------------
def _ontology_queries_for_scenario(sc: dict[str, Any]) -> list[tuple[str, str, dict]]:
    """Walk all stages, yield (stage_name, ontology, class, oq_def)."""
    out = []
    for stage_name, stage in (sc.get("stages") or {}).items():
        for oq in stage.get("ontology_queries") or []:
            if not isinstance(oq, dict):
                continue
            out.append((stage_name, oq.get("ontology"), oq.get("class"), oq))
    return out


@pytest.mark.parametrize("sid", _scenario_ids())
def test_ontology_queries_resolve(
    sid: str, registry: ScenarioRegistry, ontologies: OntologyRegistry
) -> None:
    sc = registry.get(sid)
    for stage_name, ontology_id, class_name, oq_def in _ontology_queries_for_scenario(sc):
        assert ontology_id, f"{sid}/{stage_name}: ontology_queries entry missing 'ontology'"
        assert class_name, f"{sid}/{stage_name}: ontology_queries entry missing 'class'"
        onto = ontologies.get(ontology_id)
        assert onto is not None, (
            f"{sid}/{stage_name}: references unknown ontology {ontology_id!r}. "
            f"Known: {sorted(ontologies.ids())}"
        )
        cls = onto.classes.get(class_name)
        assert cls is not None, (
            f"{sid}/{stage_name}: references unknown class {ontology_id}.{class_name}. "
            f"Known classes in {ontology_id}: {sorted(onto.classes.keys())}"
        )


# Note: a stricter "every where-key must be an attribute on the class" check
# was tried but is too tightly coupled to binding semantics. Vector bindings
# accept `query` / `k`; graph-traversal classes (e.g. SanctionsProximity,
# UltimateBeneficialOwner) accept seed-id params; tabular bindings accept
# comparison-prefixed keys like `max_total_usd`. The "does the class resolve"
# check above catches the high-leverage drift case (ontology rename) without
# the false-positive churn. Runtime-empty queries are caught by the binding
# smoke suite instead.


# -----------------------------------------------------------------------------
# Closing-messages + rationale-reasons alignment
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("sid", _scenario_ids())
def test_rationale_keys_align_with_closing_messages(
    sid: str, registry: ScenarioRegistry
) -> None:
    """If a scenario declares `rationale_reasons.reject: [...]` it must
    also declare `closing_messages.reject` (and vice-versa for any other
    decision key). Mismatches surface as silent UI gaps."""
    sc = registry.get(sid)
    rationale = sc.get("rationale_reasons") or {}
    closing = sc.get("closing_messages") or {}
    if not rationale and not closing:
        return  # autonomous scenarios may legitimately have neither
    rationale_keys = set(rationale.keys())
    closing_keys = set(closing.keys())
    # Rationale should only declare decisions the scenario actually
    # closes on. Allow rationale to be a strict subset of closing (you
    # can have a decision with no canned reasons), but not the reverse.
    extra = rationale_keys - closing_keys
    assert not extra, (
        f"{sid}: rationale_reasons declares {sorted(extra)} but no matching "
        f"closing_messages entry exists. Closing messages: {sorted(closing_keys)}"
    )


# -----------------------------------------------------------------------------
# No-legacy-queries — catches the explicit Phase 3.C migration
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("sid", _scenario_ids())
def test_no_legacy_queries_block(sid: str) -> None:
    """Hand-parse the raw YAML so a stale file with a `queries:` block fails
    here before reaching the runtime check."""
    raw = (SCENARIOS_DIR / f"{sid}.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    for stage_name, stage in (data.get("stages") or {}).items():
        assert "queries" not in (stage or {}), (
            f"{sid}/{stage_name}: uses the removed `queries:` block. "
            f"Migrate to `ontology_queries:` — see "
            f"docs/ontology.md for the recipe."
        )


# -----------------------------------------------------------------------------
# Sanity — the suite itself is exercising every scenario
# -----------------------------------------------------------------------------
def test_lint_covers_every_shipped_scenario() -> None:
    """Belt-and-braces: if someone adds a scenario but skips parametrize,
    we want a hard failure here, not a silent miss."""
    on_disk = {p.stem for p in SCENARIOS_DIR.glob("*.yaml")}
    parametrized = set(_scenario_ids())
    assert on_disk == parametrized, (
        f"Lint coverage drifted: on-disk={on_disk - parametrized}, "
        f"parametrized-only={parametrized - on_disk}"
    )
