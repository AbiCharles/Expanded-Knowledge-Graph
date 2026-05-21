"""Generate a working scenario YAML dict for an ontology class.

Phase 3.C pivot: scenarios used to be auto-generated per *data source*
(`SC-AUTO-<source_id>`). Now they're generated per *ontology class*
(`SC-ONTO-<ontology_id>-<ClassName>`), opt-in via a button in the
Mappings tab. Sources stop creating chips on register; ontology classes
do, when the operator asks.
"""
from __future__ import annotations

import re
from typing import Any

from .ontology import Mapping, Ontology


def _humanise(s: str) -> str:
    """`outcome_stats` → `outcome stats`"""
    return re.sub(r"[_\-]+", " ", s).strip()


def scenario_id_for(ontology_id: str, class_name: str) -> str:
    """The id used for SC-ONTO-* chips. Stable so re-generating overwrites
    rather than duplicating."""
    return f"SC-ONTO-{ontology_id}-{class_name}"


def _keywords_for_class(ontology_id: str, class_name: str, mapping: Mapping) -> list[str]:
    """Build a generous keyword set so likely prompts route to this chip."""
    kws: set[str] = set()
    label = _humanise(class_name).lower()
    kws.add(label)
    kws.add(class_name.lower())
    kws.add(ontology_id.lower())
    for word in label.split():
        if len(word) >= 3:
            kws.add(word)
    kws.add(f"lookup {label}")
    kws.add(f"show {label}")
    kws.add(f"list {label}")
    # Pull in source ids so prompts that mention the underlying store also route.
    cm = mapping.for_class(class_name) if mapping else None
    if cm:
        for binding in cm.sources:
            kws.add(binding.data_source.lower())
            kws.add(_humanise(binding.data_source).lower())
    return sorted(kws)


def make_ontology_scenario(
    *,
    ontology: Ontology,
    class_name: str,
    mapping: Mapping,
) -> dict[str, Any]:
    """Return a YAML dict for an autonomous lookup scenario keyed off an
    ontology class. The `proposal` stage uses an `ontology_queries:` block
    so the OntologyResolver fans out to every source the mapping covers.

    Caller validates that `class_name` exists in the ontology and that the
    mapping has at least one binding for it; this function trusts those
    preconditions.
    """
    label = _humanise(class_name)
    cm = mapping.for_class(class_name)
    binding_count = len(cm.sources) if cm else 0
    source_summary = (
        ", ".join(b.data_source for b in cm.sources) if cm else "(no bindings)"
    )

    return {
        "id": scenario_id_for(ontology.id, class_name),
        "title": f"Lookup · {label}",
        "domain": "Ontology lookups",
        "autonomous": True,
        "actor_id": "agent-data-lookup",
        "operator_role": {"label": "Operator", "name": "data.analyst"},
        "action_type": "ontology_lookup",
        "action_payload": {
            "ontology": ontology.id,
            "class": class_name,
            "scope": "data.read",
        },
        "match_keywords": _keywords_for_class(ontology.id, class_name, mapping),
        "interpreted_as": f"look up {label} via the {ontology.id} ontology",
        "clarifying_question": (
            f"Just to confirm — fetch <code>{class_name}</code> via "
            f"<code>{ontology.id}</code>, fanning out to "
            f"<code>{source_summary}</code> ({binding_count} source"
            f"{'s' if binding_count != 1 else ''}). "
            "Read-only autonomous lookup. Proceed?"
        ),
        "auto_approval_guardrail": "GR-ONTO-LOOKUP",
        "auto_approval_reason": (
            f"Read-only ontology query against {ontology.id}.{class_name}. "
            "The mapping doc governs which sources back this class; "
            "guardrail GR-ONTO-LOOKUP permits autonomous lookups."
        ),
        "closing_message": (
            f"Done — bound <code>{class_name}</code> facts via the "
            f"<code>{ontology.id}</code> ontology. Per-fact provenance is "
            "on the audit trail."
        ),
        "stages": {
            "agent_intake": {
                "binder": "OntologyLookupAgentBinder/1.0",
                "facts": [
                    {
                        "source": "kf:graph",
                        "ontology_type": "Policy",
                        "id": "POL-ONTO-LOOKUP",
                        "uri": "kf.tcs/policy/POL-ONTO-LOOKUP",
                        "title": "Autonomous ontology lookup policy",
                        "payload": (
                            "Read-only ontology queries are autonomous within "
                            "the data.read scope. The mapping doc governs which "
                            "sources are consulted."
                        ),
                    },
                    {
                        "source": "iam:scopes",
                        "ontology_type": "ActorScope",
                        "id": "agent-data-lookup",
                        "uri": "iam.tcs/actors/agent-data-lookup",
                        "title": "Actor scope",
                        "payload": (
                            f"Scopes: data.read · ontology lookup: "
                            f"{ontology.id}.{class_name}"
                        ),
                    },
                ],
            },
            "proposal": {
                "binder": "OntologyLookupProposalBinder/1.0",
                "ontology_queries": [
                    {
                        "ontology": ontology.id,
                        "class": class_name,
                        "where": {},
                        "purpose": (
                            f"Lookup against ontology class {ontology.id}.{class_name}"
                        ),
                    }
                ],
            },
        },
        "outcomes": {
            "auto_execute": {
                "headline": f"Auto-executed — {class_name} fetched via {ontology.id}",
                "detail": (
                    f"Lookup against {ontology.id}.{class_name} completed via "
                    f"{binding_count} source binding"
                    f"{'s' if binding_count != 1 else ''}. Rows are bound to "
                    "the case envelope and recorded in the audit trail."
                ),
            },
        },
        # Marker so the API can distinguish ontology-generated scenarios for cleanup.
        "_auto_for_ontology_class": [ontology.id, class_name],
        # Tells the orchestrator to pre-parse the prompt and merge any
        # extracted where filters into this chip's empty `where: {}` —
        # makes "show me Dutch suppliers" actually filter the lookup
        # instead of returning every Supplier.
        "_filter_from_prompt": True,
        "_custom_suggested_prompt": f"Look up {label} (via {ontology.id})",
    }


def suggested_prompt_for_class(ontology_id: str, class_name: str) -> str:
    label = _humanise(class_name)
    return f"Look up {label} (via {ontology_id})"
