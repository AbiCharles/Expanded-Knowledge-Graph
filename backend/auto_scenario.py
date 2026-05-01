"""Generate a working scenario YAML dict from a user-added data source.

Strategy: every operator-registered SQLite/Postgres/CSV source gets a small
autonomous scenario `SC-AUTO-<source_id>` so the agent can pull from it on
demand. The chip appears in the operator console immediately — no YAML
authoring required.

These auto-scenarios:
  - are autonomous (read-only data lookup, no human review)
  - have one binder stage (proposal) that runs a `queries:` block against
    the source
  - derive `match_keywords` from the source id and ontology types so prompts
    like "lookup outcome stats" route correctly
"""
from __future__ import annotations

import re
from typing import Any

from .datasources import DataSourceSpec


def _humanise(source_id: str) -> str:
    """`outcome_stats` → `outcome stats`"""
    return re.sub(r"[_\-]+", " ", source_id).strip()


def _keywords_from_source(spec: DataSourceSpec, ontology_types: list[str]) -> list[str]:
    """Build a generous keyword set so likely prompts route to this chip."""
    kws: set[str] = set()
    base = _humanise(spec.id).lower()
    kws.add(spec.id.lower())
    kws.add(base)
    for word in base.split():
        if len(word) >= 3:
            kws.add(word)
    for ot in ontology_types:
        kws.add(ot.lower())
        kws.add(_humanise(ot).lower())
    kws.add(f"lookup {base}")
    kws.add(f"query {base}")
    kws.add(f"show {base}")
    return sorted(kws)


def _ontology_types_for_source(spec: DataSourceSpec) -> list[str]:
    cfg = spec.config
    if spec.kind in ("sqlite", "postgres"):
        return list((cfg.get("queries") or {}).keys())
    if spec.kind == "csv":
        return [cfg.get("ontology_type", "Record")]
    if spec.kind == "http":
        return list((cfg.get("paths") or {}).keys())
    if spec.kind == "vector_store":
        return [cfg.get("ontology_type", "PolicyExcerpt")]
    return []


def _query_block_for(spec: DataSourceSpec, ontology_type: str) -> dict[str, Any]:
    base = {
        "data_source": spec.id,
        "ontology_type": ontology_type,
        "purpose": f"Lookup against operator-registered source {spec.id}",
    }
    # Sensible default filters per kind so the query has something to run on.
    if spec.kind in ("sqlite", "postgres"):
        # Defer to the resolver's :max_results binding; no other params by default.
        base["filter"] = {}
    elif spec.kind == "vector_store":
        base["filter"] = {"query": _humanise(spec.id), "top_k": 3}
    elif spec.kind == "http":
        base["filter"] = {"id": "1"}  # most demo APIs accept id=1
    elif spec.kind == "csv":
        base["filter"] = {}
    return base


def make_auto_scenario(spec: DataSourceSpec) -> dict[str, Any]:
    """Return a YAML dict for an autonomous lookup scenario."""
    label = _humanise(spec.id)
    ontology_types = _ontology_types_for_source(spec)
    primary_ot = ontology_types[0] if ontology_types else "Record"

    return {
        "id": f"SC-AUTO-{spec.id}",
        "title": f"Lookup · {label}",
        "domain": "Custom data sources",
        "autonomous": True,
        "actor_id": "agent-data-lookup",
        "operator_role": {"label": "Operator", "name": "data.analyst"},
        "action_type": "data_lookup",
        "action_payload": {
            "source_id": spec.id,
            "ontology_type": primary_ot,
            "scope": "data.read",
        },
        "match_keywords": _keywords_from_source(spec, ontology_types),
        "interpreted_as": f"look up data from {label}",
        "clarifying_question": (
            f"Just to confirm — pull data from <code>{spec.id}</code> "
            f"({spec.kind}). Read-only query within my <code>data.read</code> scope; "
            f"per policy <code>GR-AUTO-LOOKUP</code> no human review is required. Proceed?"
        ),
        "auto_approval_guardrail": "GR-AUTO-LOOKUP",
        "auto_approval_reason": (
            f"Read-only query against operator-registered source {spec.id!r}. "
            "Policy GR-AUTO-LOOKUP permits autonomous lookups against trusted operator sources."
        ),
        "closing_message": (
            f"Done — pulled rows from <code>{spec.id}</code>. The result is on the audit trail."
        ),
        "stages": {
            "agent_intake": {
                "binder": "AutoLookupAgentBinder/1.0",
                "facts": [
                    {
                        "source": "kf:graph",
                        "ontology_type": "Policy",
                        "id": "POL-AUTO-LOOKUP",
                        "uri": "kf.tcs/policy/POL-AUTO-LOOKUP",
                        "title": "Autonomous data lookup policy",
                        "payload": (
                            "Read-only queries against operator-registered data sources are "
                            "autonomous within the data.read scope."
                        ),
                    },
                    {
                        "source": "iam:scopes",
                        "ontology_type": "ActorScope",
                        "id": "agent-data-lookup",
                        "uri": "iam.tcs/actors/agent-data-lookup",
                        "title": "Actor scope",
                        "payload": (
                            f"Scopes: data.read · operator-registered source: {spec.id}"
                        ),
                    },
                ],
            },
            "proposal": {
                "binder": "AutoLookupProposalBinder/1.0",
                "queries": [_query_block_for(spec, primary_ot)],
            },
        },
        "outcomes": {
            "auto_execute": {
                "headline": f"Auto-executed — data retrieved from {spec.id}",
                "detail": (
                    f"Lookup against {spec.id} ({spec.kind}) completed. Rows are bound to the "
                    "case envelope and recorded in the audit trail."
                ),
            },
        },
        # Marker so the API can distinguish auto-generated scenarios for cleanup.
        "_auto_for_source": spec.id,
    }


def suggested_prompt_for(spec: DataSourceSpec) -> str:
    label = _humanise(spec.id)
    return f"Look up data from {label}"
