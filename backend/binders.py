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
from .ontology import (
    OntologyQuery,
    OntologyResolver,
    substitute_payload_refs,
)
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
    ontology: Optional[OntologyResolver] = None,
    payload: Optional[dict[str, Any]] = None,
) -> tuple[list[KnowledgeFact], list[KnowledgeQuery]]:
    """Read `facts:` (inline) and `ontology_queries:` (ontology classes)
    from a stage definition. Return the combined facts plus the list of
    KnowledgeQuery objects issued (recorded in lineage).

    Phase 3.C dropped the legacy `queries:` block — scenarios that still
    use it raise at load time via `validate_scenario_no_legacy_queries`.

    `payload` is `action.payload` when available — used to substitute
    `:param`-prefixed values in `ontology_queries.where` clauses.

    The unused `sources` parameter is kept on the signature so callers
    constructed before 3.C don't crash; future cleanup can drop it.
    """
    del sources  # legacy; the ontology resolver handles all data dispatch
    facts: list[KnowledgeFact] = list(_facts_from_inline(stage_def.get("facts", [])))
    queries_issued: list[KnowledgeQuery] = []

    # Track which query produced each fact so the UI's "query plan" panel
    # can highlight cards on click. Inline facts (from `facts:`) have no
    # originating query and stay un-tagged.
    for query_index, oq_def in enumerate(stage_def.get("ontology_queries", []) or []):
        if ontology is None:
            log.warning(
                "ontology_queries: declared but no OntologyResolver available"
            )
            break
        try:
            where = substitute_payload_refs(
                oq_def.get("where", {}) or {}, payload or {}
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "ontology_queries entry skipped — payload substitution failed: %s",
                exc,
            )
            continue

        # Phase 3.E enhancement: merge prompt-extracted filters
        # (populated by the orchestrator for `_filter_from_prompt: true`
        # scenarios) when the parsed class matches THIS query's class.
        # `setdefault` so an explicit where in the YAML always wins over
        # an LLM-extracted one.
        prompt_filters_by_target = (payload or {}).get("__prompt_filters__") or {}
        target_key = f"{oq_def['ontology']}.{oq_def['class']}"
        for k, v in (prompt_filters_by_target.get(target_key) or {}).items():
            if v is None:
                continue
            where.setdefault(k, v)

        oq = OntologyQuery(
            ontology=oq_def["ontology"],
            **{"class": oq_def["class"]},
            where=where,
            include_relations=list(oq_def.get("include_relations", []) or []),
            max_results=int(oq_def.get("max_results", 50)),
            purpose=oq_def.get("purpose", "") or "",
        )
        queries_issued.append(
            KnowledgeQuery(
                ontology_type=oq.class_,
                filters={"__ontology__": oq.ontology, **oq.where},
                requested_by=stage_def.get("binder", "binder"),
                purpose=oq.purpose or f"Ontology query: {oq.ontology}.{oq.class_}",
                max_results=oq.max_results,
            )
        )
        # Match the raw `queries:` branch above: any failure (missing ontology,
        # missing mapping, resolver crash) degrades to a logged warning + zero
        # facts from this entry, so the orchestrator's case task never crashes.
        try:
            new_facts = ontology.resolve_query(oq)
            # Tag each fact with the originating query index so the API
            # serializer + frontend can correlate them. Mutates the payload
            # in-place — safe because the resolver returns fresh dicts.
            for f in new_facts:
                f.payload["query_index"] = query_index
            facts.extend(new_facts)
            log.info(
                "binder ontology query → %s.%s returned %d fact(s)",
                oq.ontology, oq.class_, len(new_facts),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "binder ontology_query against %s.%s failed: %s",
                oq.ontology, oq.class_, exc,
            )

    return facts, queries_issued


# =============================================================================
# Binders
# =============================================================================
class FixtureAgentBinder:
    def __init__(
        self,
        scenarios: ScenarioRegistry,
        sources: Optional[DataSourceRegistry] = None,
        ontology: Optional[OntologyResolver] = None,
    ):
        self._scenarios = scenarios
        self._sources = sources
        self._ontology = ontology

    def bind(self, agent_id: str, scenario: dict[str, Any]) -> StageContext:
        scenario_id = scenario["scenario_id"]
        sc = self._scenarios.require(scenario_id)
        stage_def = sc["stages"]["agent_intake"]
        # Intake fires before action drafting, so action.payload isn't
        # available — we expose the scenario's static action_payload as
        # the substitution context, mirroring what attach_proposal will do.
        intake_payload = dict(sc.get("action_payload") or {})
        facts, queries_issued = _facts_from_stage(
            stage_def,
            sources=self._sources,
            ontology=self._ontology,
            payload=intake_payload,
        )
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
    def __init__(
        self,
        scenarios: ScenarioRegistry,
        sources: Optional[DataSourceRegistry] = None,
        ontology: Optional[OntologyResolver] = None,
    ):
        self._scenarios = scenarios
        self._sources = sources
        self._ontology = ontology

    def bind(self, action: AgentAction) -> StageContext:
        scenario_id = action.payload.get("__scenario_id__")
        if not scenario_id:
            raise RuntimeError(
                "AgentAction.payload missing __scenario_id__ — orchestrator must set this"
            )
        sc = self._scenarios.require(scenario_id)
        stage_def = sc["stages"]["proposal"]
        facts, queries_issued = _facts_from_stage(
            stage_def,
            sources=self._sources,
            ontology=self._ontology,
            payload=dict(action.payload),
        )
        return StageContext(
            stage=Stage.PROPOSAL,
            facts=facts,
            queries_issued=queries_issued,
            bound_by=stage_def["binder"],
            notes=f"Bound to scenario {scenario_id}",
        )


class FixtureReviewBinder:
    def __init__(
        self,
        scenarios: ScenarioRegistry,
        sources: Optional[DataSourceRegistry] = None,
        ontology: Optional[OntologyResolver] = None,
    ):
        self._scenarios = scenarios
        self._sources = sources
        self._ontology = ontology

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
        facts, queries_issued = _facts_from_stage(
            stage_def,
            sources=self._sources,
            ontology=self._ontology,
            payload=dict(action.payload),
        )
        return StageContext(
            stage=Stage.REVIEW,
            facts=facts,
            queries_issued=queries_issued,
            bound_by=stage_def["binder"],
            notes=f"Reviewer evidence package for scenario {scenario_id}",
        )
