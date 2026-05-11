"""OntologyResolver — dispatches ontology-class queries across the
underlying KnowledgeResolvers registered in DataSourceRegistry.

Phase 1 semantics (kept intentionally narrow):

  - Look up the class in the ontology, look up its mapping.
  - For each SourceBinding in the mapping:
      1. Translate the user's `where` (ontology attribute names) into
         the source's column names via `attribute_map`.
      2. Call the underlying resolver via `DataSourceRegistry`.
      3. Tag returned facts with `payload["via_ontology"]` and
         `payload["via_source_binding"]` so reviewers and the playground
         see both intent and provenance.
  - Concatenate all facts. **No cross-source dedupe in v1** — see
    `docs/ontology.md` for the rationale.

Out of Phase 1 scope (deliberately):
  - `include_relations` traversal
  - LLM-based mapping suggestions
  - Output payload column-renaming (the underlying resolver builds the
    payload; we tag but don't reshape)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from tcs_hitl_context import KnowledgeFact, KnowledgeQuery

from ..datasources import DataSourceRegistry
from .loader import OntologyRegistry
from .models import OntologyQuery

log = logging.getLogger(__name__)


class OntologyResolveError(Exception):
    """Raised on unrecoverable resolve-time errors (missing class, missing
    mapping). Per-source binding failures are logged and skipped — empty
    results are returned only if every binding fails."""


class OntologyResolver:
    """Implements the framework's KnowledgeResolver Protocol.

    Constructed once in `state.py` and passed directly to the binders.
    Not registered in `DataSourceRegistry` — the binders call
    `resolve_query()` explicitly when they see an `ontology_queries:`
    block in a stage.
    """

    name = "ontology"

    def __init__(self, ontologies: OntologyRegistry, sources: DataSourceRegistry):
        self._ontologies = ontologies
        self._sources = sources

    # -------------------------------------------------------------------------
    # Protocol-compatible entry point
    # -------------------------------------------------------------------------
    def resolve(self, query: KnowledgeQuery) -> list[KnowledgeFact]:
        """KnowledgeResolver Protocol entry. The framework's KnowledgeQuery
        doesn't carry an ontology id, so this method requires the caller to
        embed it in `query.filters['__ontology__']`. Most callers should
        use `resolve_query()` instead."""
        ontology_id = query.filters.get("__ontology__")
        if not ontology_id:
            raise OntologyResolveError(
                "OntologyResolver.resolve requires filters['__ontology__'] — "
                "use resolve_query(OntologyQuery) instead"
            )
        where = {k: v for k, v in query.filters.items() if k != "__ontology__"}
        oq = OntologyQuery(
            ontology=ontology_id,
            **{"class": query.ontology_type},
            where=where,
            max_results=query.max_results,
            purpose=query.purpose,
        )
        return self.resolve_query(oq)

    # -------------------------------------------------------------------------
    # Richer entry point (binders + playground use this)
    # -------------------------------------------------------------------------
    def resolve_query(self, oq: OntologyQuery) -> list[KnowledgeFact]:
        ontology = self._ontologies.require(oq.ontology)
        cls = ontology.class_(oq.class_)
        if cls is None:
            raise OntologyResolveError(
                f"class {oq.class_!r} not in ontology {oq.ontology!r}"
            )
        mapping_doc = self._ontologies.get_mapping(oq.ontology)
        if mapping_doc is None:
            raise OntologyResolveError(
                f"ontology {oq.ontology!r} has no mapping document"
            )
        class_mapping = mapping_doc.for_class(oq.class_)
        if class_mapping is None or not class_mapping.sources:
            raise OntologyResolveError(
                f"class {oq.class_!r} has no source bindings in mapping"
            )

        via_tag = f"{oq.ontology}.{oq.class_}"
        all_facts: list[KnowledgeFact] = []
        bindings_attempted = 0
        bindings_failed = 0

        for binding in class_mapping.sources:
            bindings_attempted += 1
            try:
                resolver = self._sources.require(binding.data_source)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "ontology %s: source %s not registered, skipping (%s)",
                    via_tag, binding.data_source, exc,
                )
                bindings_failed += 1
                continue

            translated_filters = self._translate_filters(oq.where, binding.attribute_map)
            # Attach the binding under a private key so binding-aware
            # connectors (Phase 3.C) can read `table` / `query_template` /
            # `http_path_template` / `identifier_column` without a separate
            # parameter on the resolver Protocol. Connectors that don't
            # know about it just ignore the unknown key.
            translated_filters["__binding__"] = {
                "data_source": binding.data_source,
                "identifier_column": binding.identifier_column,
                "attribute_map": binding.attribute_map,
                "table": binding.table,
                "query_template": binding.query_template,
                "http_path_template": binding.http_path_template,
            }
            kq = KnowledgeQuery(
                ontology_type=oq.class_,
                filters=translated_filters,
                requested_by="ontology_resolver",
                purpose=oq.purpose or f"Ontology query: {via_tag}",
                max_results=oq.max_results,
            )
            try:
                facts = resolver.resolve(kq)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "ontology %s: resolver %s raised %s",
                    via_tag, binding.data_source, exc,
                )
                bindings_failed += 1
                continue

            for f in facts:
                tagged = f.model_copy(deep=True)
                tagged.payload["via_ontology"] = via_tag
                tagged.payload["via_source_binding"] = binding.data_source
                all_facts.append(tagged)

        if bindings_attempted > 0 and bindings_failed == bindings_attempted:
            log.warning(
                "ontology %s: every source binding failed (%d/%d)",
                via_tag, bindings_failed, bindings_attempted,
            )
        return all_facts

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    @staticmethod
    def _translate_filters(
        where: dict[str, Any], attribute_map: dict[str, str]
    ) -> dict[str, Any]:
        """Rename ontology-attribute keys to source-column keys.

        Keys with no entry in `attribute_map` are passed through unchanged
        — this keeps source-native filter knobs (e.g. CSV column names that
        don't have an ontology attribute) usable from the playground.
        """
        if not attribute_map:
            return dict(where)
        out: dict[str, Any] = {}
        for k, v in where.items():
            out[attribute_map.get(k, k)] = v
        return out


def substitute_payload_refs(where: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Replace `:foo` values with `payload['foo']`.

    Used by binders so scenario authors can write
    `where: { supplier_id: ":supplier_id" }` and have it resolved at
    bind time against the action payload. Values that don't look like
    `:name` are passed through. Missing payload keys raise — silent
    None substitution would mask scenario authoring bugs.
    """
    if not where:
        return {}
    out: dict[str, Any] = {}
    for k, v in where.items():
        if isinstance(v, str) and v.startswith(":") and len(v) > 1:
            key = v[1:]
            if key not in payload:
                raise OntologyResolveError(
                    f"ontology where-clause references {v!r} but payload has no {key!r}"
                )
            out[k] = payload[key]
        else:
            out[k] = v
    return out
