"""End-to-end smoke: every ontology_query in every shipped scenario must
return ≥1 row against the canned demo dataset.

Why this matters: the runtime is forgiving — a binder failure logs a
warning and returns zero facts. The demo silently shows an empty card
grid. This test fails loud at CI time instead.

Scope: only ontology_queries that don't require runtime-only payload
substitution (no `:param`-prefixed where values, no
`__prompt_filters__`). Those need a fully orchestrated case to resolve;
they're covered by `test_cases.py`. This smoke covers the rest — which
is the majority of shipped queries.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from backend.datasources import DataSourceRegistry
from backend.ontology import OntologyRegistry
from backend.ontology.models import OntologyQuery
from backend.ontology.resolver import OntologyResolver


REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = REPO_ROOT / "backend" / "scenarios"
ONTOLOGIES_DIR = REPO_ROOT / "backend" / "ontologies"
SOURCES_YAML = REPO_ROOT / "backend" / "data" / "sources.yaml"


@pytest.fixture(scope="module")
def ontologies() -> OntologyRegistry:
    return OntologyRegistry.from_directory(ONTOLOGIES_DIR)


@pytest.fixture(scope="module")
def sources() -> DataSourceRegistry:
    return DataSourceRegistry.from_yaml(
        storage_path=SOURCES_YAML,
        project_root=REPO_ROOT,
        openai_api_key=None,  # any class with a vector binding will be skipped
    )


@pytest.fixture(scope="module")
def resolver(ontologies: OntologyRegistry, sources: DataSourceRegistry) -> OntologyResolver:
    """One resolver wired against the repo's seeded data sources +
    ontologies. Module-scoped because the resolver is read-only and
    booting it is the expensive bit."""
    return OntologyResolver(ontologies=ontologies, sources=sources)


def _binding_source_ids(
    ontologies: OntologyRegistry, ontology_id: str, class_name: str
) -> list[str]:
    """The data_source ids the (ontology, class) binding depends on.
    Empty list = no binding configured (e.g. vector classes with sources: []).
    """
    mapping = ontologies.get_mapping(ontology_id)
    if mapping is None:
        return []
    cls_mapping = mapping.mappings.get(class_name)
    if cls_mapping is None:
        return []
    return [b.data_source for b in (cls_mapping.sources or [])]


# Meta-tooling scenarios that intentionally query empty state — their job
# is to demonstrate "this table is clear" rather than to render evidence
# cards. Excluded from the >= 1 fact assertion.
_META_SCENARIO_IDS = {
    "SC-LN-DEMO-RESET-999",
}


def _static_ontology_queries() -> list[tuple[str, str, dict[str, Any]]]:
    """Yield (scenario_id, stage_name, oq_def) for every ontology_query
    whose `where:` is fully static (no `:param` substitutions and no
    sentinel keys)."""
    out: list[tuple[str, str, dict[str, Any]]] = []
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        sid = data["id"]
        if sid in _META_SCENARIO_IDS:
            continue
        for stage_name, stage in (data.get("stages") or {}).items():
            for oq in stage.get("ontology_queries") or []:
                where = oq.get("where") or {}
                # Skip queries that depend on payload-time substitution.
                has_param = any(
                    isinstance(v, str) and v.startswith(":")
                    for v in where.values()
                )
                if has_param:
                    continue
                # Skip the prompt-filter sentinel — it's runtime-only.
                if any(k.startswith("__") for k in where.keys()):
                    continue
                out.append((sid, stage_name, oq))
    return out


_STATIC_QUERIES = _static_ontology_queries()


def _query_id(triple: tuple[str, str, dict[str, Any]]) -> str:
    sid, stage, oq = triple
    return f"{sid}::{stage}::{oq.get('ontology')}.{oq.get('class')}"


@pytest.mark.parametrize("triple", _STATIC_QUERIES, ids=[_query_id(t) for t in _STATIC_QUERIES])
def test_static_ontology_query_returns_at_least_one_fact(
    triple: tuple[str, str, dict[str, Any]],
    resolver: OntologyResolver,
    ontologies: OntologyRegistry,
    sources: DataSourceRegistry,
) -> None:
    sid, stage_name, oq_def = triple
    ontology_id = oq_def["ontology"]
    class_name = oq_def["class"]

    # Pre-flight: skip queries whose binding requires a data source that
    # isn't registered in this environment (Neo4j needs NEO4J_URI; vector
    # bindings need OpenAI; some classes have `sources: []` and are
    # runtime-injected by the orchestrator). The point of this test is to
    # catch scenario-to-binding drift, NOT to assert external infra exists.
    binding_sources = _binding_source_ids(ontologies, ontology_id, class_name)
    if not binding_sources:
        pytest.skip(
            f"{sid}/{stage_name}: {ontology_id}.{class_name} has no source binding "
            "(runtime-injected or intentionally unmapped)"
        )
    for src_id in binding_sources:
        if sources.get(src_id) is None:
            pytest.skip(
                f"{sid}/{stage_name}: data source {src_id!r} not registered in CI "
                f"(needed by {ontology_id}.{class_name})"
            )

    oq = OntologyQuery(
        ontology=ontology_id,
        **{"class": class_name},
        where=oq_def.get("where") or {},
        include_relations=list(oq_def.get("include_relations") or []),
        max_results=int(oq_def.get("max_results", 50)),
        purpose=oq_def.get("purpose") or "",
    )
    try:
        facts = resolver.resolve_query(oq)
    except Exception as exc:  # noqa: BLE001
        # Last-resort guard: any unexpected external-infra error degrades to skip.
        msg = str(exc).lower()
        if any(needle in msg for needle in ("openai", "neo4j", "connection")):
            pytest.skip(f"{sid}/{stage_name}: external binding unavailable in CI ({exc})")
        raise

    assert len(facts) >= 1, (
        f"{sid}/{stage_name}: ontology query "
        f"{oq.ontology}.{oq.class_} where={oq.where} returned 0 facts against "
        f"the seeded demo dataset. The demo card grid would be empty for this stage."
    )


def test_smoke_covered_a_meaningful_share_of_queries() -> None:
    """Belt-and-braces: if the static-query filter ever excludes everything
    (e.g. a refactor renames the param sigil), fail loud here instead of
    pretending we have coverage."""
    assert len(_STATIC_QUERIES) >= 5, (
        f"static-query filter selected only {len(_STATIC_QUERIES)} queries — "
        f"likely a filter regression"
    )
