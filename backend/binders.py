"""Fixture-driven implementations of the framework's three binder Protocols.

Each binder reads a stage definition from a scenario YAML. A stage may contain
either:

  facts:    inline literal facts (kept for the demo's stable mock data)
  queries:  list of queries against registered DataSources (live data)

Both blocks coexist; a stage can mix the two. The combined facts go into the
StageContext, with one KnowledgeQuery recorded per `queries:` entry so the
lineage shows what was asked.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from tcs_hitl_context import (
    AgentAction,
    KnowledgeContext,
    KnowledgeFact,
    KnowledgeQuery,
    KnowledgeRef,
    Stage,
    StageContext,
)

from .datasources import DataSourceRegistry
from .scenario_loader import ScenarioRegistry

log = logging.getLogger(__name__)


# =============================================================================
# Helpers
# =============================================================================
def _facts_from_inline(rows: list[dict[str, Any]]) -> list[KnowledgeFact]:
    out: list[KnowledgeFact] = []
    for row in rows:
        ref = KnowledgeRef(
            source=row["source"],
            ontology_type=row["ontology_type"],
            id=row["id"],
            uri=row.get("uri"),
        )
        out.append(
            KnowledgeFact(
                ref=ref,
                payload={"title": row["title"], "summary": row["payload"]},
                fetched_by="fixture_resolver",
            )
        )
    return out


def _facts_from_stage(
    stage_def: dict[str, Any],
    *,
    sources: Optional[DataSourceRegistry] = None,
) -> tuple[list[KnowledgeFact], list[KnowledgeQuery]]:
    """Read both `facts:` (inline) and `queries:` (live). Return (facts, queries_issued)."""
    facts: list[KnowledgeFact] = list(_facts_from_inline(stage_def.get("facts", [])))
    queries_issued: list[KnowledgeQuery] = []

    for q in stage_def.get("queries", []) or []:
        if sources is None:
            log.warning("queries: declared but no DataSourceRegistry available")
            break
        source_id = q["data_source"]
        kq = KnowledgeQuery(
            ontology_type=q["ontology_type"],
            filters=q.get("filter", {}) or {},
            requested_by=stage_def.get("binder", "binder"),
            purpose=q.get("purpose", ""),
            max_results=int(q.get("max_results", 50)),
        )
        queries_issued.append(kq)
        try:
            resolver = sources.require(source_id)
            new_facts = resolver.resolve(kq)
            facts.extend(new_facts)
            log.info(
                "binder query → %s.%s returned %d fact(s)",
                source_id, q["ontology_type"], len(new_facts),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "binder query against %s/%s failed: %s",
                source_id, q.get("ontology_type"), exc,
            )

    return facts, queries_issued


# =============================================================================
# Binders
# =============================================================================
class FixtureAgentBinder:
    def __init__(self, scenarios: ScenarioRegistry, sources: Optional[DataSourceRegistry] = None):
        self._scenarios = scenarios
        self._sources = sources

    def bind(self, agent_id: str, scenario: dict[str, Any]) -> StageContext:
        scenario_id = scenario["scenario_id"]
        sc = self._scenarios.require(scenario_id)
        stage_def = sc["stages"]["agent_intake"]
        facts, queries_issued = _facts_from_stage(stage_def, sources=self._sources)
        if not queries_issued:
            queries_issued = [
                KnowledgeQuery(
                    ontology_type="Policy",
                    filters={"scenario_id": scenario_id},
                    requested_by="agent_intake_binder",
                    purpose="Surface active policy + actor scope",
                ),
            ]
        return StageContext(
            stage=Stage.AGENT_INTAKE,
            facts=facts,
            queries_issued=queries_issued,
            bound_by=stage_def["binder"],
        )


class FixtureProposalBinder:
    def __init__(self, scenarios: ScenarioRegistry, sources: Optional[DataSourceRegistry] = None):
        self._scenarios = scenarios
        self._sources = sources

    def bind(self, action: AgentAction) -> StageContext:
        scenario_id = action.payload.get("__scenario_id__")
        if not scenario_id:
            raise RuntimeError(
                "AgentAction.payload missing __scenario_id__ — orchestrator must set this"
            )
        sc = self._scenarios.require(scenario_id)
        stage_def = sc["stages"]["proposal"]
        facts, queries_issued = _facts_from_stage(stage_def, sources=self._sources)
        return StageContext(
            stage=Stage.PROPOSAL,
            facts=facts,
            queries_issued=queries_issued,
            bound_by=stage_def["binder"],
            notes=f"Bound to scenario {scenario_id}",
        )


class FixtureReviewBinder:
    def __init__(self, scenarios: ScenarioRegistry, sources: Optional[DataSourceRegistry] = None):
        self._scenarios = scenarios
        self._sources = sources

    def bind(self, action: AgentAction, prior: KnowledgeContext) -> StageContext:
        scenario_id = action.payload.get("__scenario_id__")
        if not scenario_id:
            raise RuntimeError("AgentAction.payload missing __scenario_id__")
        sc = self._scenarios.require(scenario_id)
        stages = sc.get("stages", {})
        if "review" not in stages:
            raise RuntimeError(
                f"Scenario {scenario_id} has no review stage — should not have reached HITL"
            )
        stage_def = stages["review"]
        facts, queries_issued = _facts_from_stage(stage_def, sources=self._sources)
        return StageContext(
            stage=Stage.REVIEW,
            facts=facts,
            queries_issued=queries_issued,
            bound_by=stage_def["binder"],
            notes=f"Reviewer evidence package for scenario {scenario_id}",
        )
