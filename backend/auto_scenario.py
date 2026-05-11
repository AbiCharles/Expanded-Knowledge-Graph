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


# =============================================================================
# Ad-hoc write-action scenario (Phase 3.E — NL→write-action fallback)
# =============================================================================
NLWRITE_PREFIX = "SC-NLWRITE-"


def nlwrite_scenario_id_for(case_id: str) -> str:
    return f"{NLWRITE_PREFIX}{case_id}"


def make_nlwrite_action_scenario(
    *,
    case_id: str,
    action,  # backend.actions.Action
    arguments: dict[str, Any],
    rationale: str,
    prompt: str,
) -> dict[str, Any]:
    """Synthesize an HITL scenario whose reviewer approves running an
    operator-NL-picked write action. The action's executor is recorded
    in the scenario's `_executor` block; the orchestrator runs it on
    approve.
    """
    target = getattr(action.executor, "data_source", "(unspecified)")
    arg_summary = ", ".join(f"{k}={v}" for k, v in arguments.items()) or "(no args)"
    return {
        "id": nlwrite_scenario_id_for(case_id),
        "title": f"NL write · {action.title}",
        "domain": "Ad-hoc write actions",
        "autonomous": not action.hitl,  # HITL by default
        "actor_id": "agent-write-actions",
        "operator_role": {"label": "Operator", "name": "data.analyst"},
        "reviewer_role": (
            {"label": "Reviewer", "name": "ops.reviewer"} if action.hitl else None
        ),
        "teams_channel": "#nl-writes",
        "teams_headline": f"NL write — {action.title}",
        "execute_message": (
            f"The agent will execute <strong>{action.id}</strong> "
            f"against <code>{target}</code> with arguments "
            f"<code>{arg_summary}</code>."
        ),
        "action_type": "nl_write_action",
        "action_payload": {
            "action_id": action.id,
            "arguments": arguments,
            "scope": "data.write",
        },
        "match_keywords": [],
        "interpreted_as": (
            rationale or f"run write action {action.id} via {action.executor.kind}"
        ),
        "clarifying_question": (
            f"Routed via the action registry — picked "
            f"<code>{action.id}</code> ({action.executor.kind} → "
            f"<code>{target}</code>) with arguments <code>{arg_summary}</code>. "
            "Submit for reviewer approval?"
        ),
        "closing_messages": {
            "approve": (
                "Reviewer approved. Action executed; outcome on the audit trail."
            ),
            "reject": (
                "Reviewer rejected. The action was not executed. "
                "Reason: <em>\"{rationale}\"</em>"
            ),
            "request_more_info": (
                "Reviewer needs more information before deciding. "
                "Specifically: <em>\"{rationale}\"</em>"
            ),
        },
        "rationale_reasons": {
            "reject": [
                "Arguments look wrong or risky",
                "Action would affect the wrong row(s)",
                "Operator should re-phrase the prompt",
            ],
            "request_more_info": [
                "Confirm the source target",
                "Confirm the argument values were extracted correctly",
            ],
        },
        "stages": {
            "agent_intake": {
                "binder": "NLWriteAgentBinder/1.0",
                "facts": [
                    {
                        "source": "kf:graph",
                        "ontology_type": "Policy",
                        "id": "POL-NL-WRITE",
                        "uri": "kf.tcs/policy/POL-NL-WRITE",
                        "title": "NL write-action policy",
                        "payload": (
                            "Write actions picked from natural language are "
                            "HITL by default; the reviewer approves before "
                            "the executor runs."
                        ),
                    },
                    {
                        "source": "iam:scopes",
                        "ontology_type": "ActorScope",
                        "id": "agent-write-actions",
                        "uri": "iam.tcs/actors/agent-write-actions",
                        "title": "Actor scope",
                        "payload": (
                            f"Scopes: data.write · proposed action: {action.id}"
                        ),
                    },
                ],
            },
            "proposal": {
                "binder": "NLWriteProposalBinder/1.0",
                "facts": [
                    {
                        "source": "actions:registry",
                        "ontology_type": "WriteAction",
                        "id": action.id,
                        "uri": f"actions/{action.id}",
                        "title": action.title,
                        "payload": (
                            f"executor={action.executor.kind} target={target} "
                            f"arguments=({arg_summary})"
                        ),
                    },
                ],
            },
            "review": {
                "binder": "NLWriteReviewBinder/1.0",
                "facts": [
                    {
                        "source": "actions:registry",
                        "ontology_type": "ActionPreview",
                        "id": f"{action.id}-preview",
                        "uri": f"actions/{action.id}",
                        "title": "Proposed call",
                        "payload": (
                            f"{action.executor.kind} on {target} with "
                            f"arguments {arg_summary}. Reviewer approves to "
                            "actually run."
                        ),
                    },
                ],
            },
        }
        if action.hitl
        else {
            "agent_intake": {
                "binder": "NLWriteAgentBinder/1.0",
                "facts": [],
            },
            "proposal": {
                "binder": "NLWriteProposalBinder/1.0",
                "facts": [
                    {
                        "source": "actions:registry",
                        "ontology_type": "WriteAction",
                        "id": action.id,
                        "title": action.title,
                        "payload": (
                            f"executor={action.executor.kind} target={target} "
                            f"arguments=({arg_summary})"
                        ),
                    },
                ],
            },
        },
        "outcomes": {
            "approve": {
                "headline": f"Approved — {action.title}",
                "detail": "Reviewer approved; executor invoked; outcome on case.",
            },
            "reject": {
                "headline": "Rejected — write action aborted",
                "detail": "Reviewer rejected; nothing was executed.",
            },
            "request_more_info": {
                "headline": "More information requested",
                "detail": "Reviewer asked for more context before deciding.",
            },
            "auto_execute": {
                "headline": f"Auto-executed — {action.title}",
                "detail": "Action ran without HITL (action.hitl=false). Outcome on case.",
            },
        },
        "auto_approval_guardrail": "GR-NLWRITE-AUTO" if not action.hitl else None,
        "auto_approval_reason": (
            "Action declared hitl=false at registration time."
            if not action.hitl
            else None
        ),
        # Markers used by the chip-list filter and the orchestrator's
        # post-decision executor hook.
        "_nlwrite": True,
        "_executor": {
            "action_id": action.id,
            "arguments": arguments,
        },
        "_custom_suggested_prompt": prompt[:80] if prompt else action.title,
    }


# =============================================================================
# Ad-hoc ontology fallback (Phase 3.D — NL→ontology in the main composer)
# =============================================================================
ADHOC_PREFIX = "SC-ADHOC-"


def adhoc_scenario_id_for(case_id: str) -> str:
    """Synthetic id stable per-case so the orchestrator's repeated
    `scenarios.require()` lookups during binding always find the same dict.
    Hidden from the chip list via the `_adhoc: True` marker."""
    return f"{ADHOC_PREFIX}{case_id}"


def make_adhoc_ontology_scenario(
    *,
    case_id: str,
    ontology_id: str,
    class_name: str,
    where: dict[str, Any],
    purpose: str,
    prompt: str,
) -> dict[str, Any]:
    """One-shot ephemeral scenario the cases API synthesizes when the
    operator opted in to NL→ontology fallback and the scenario classifier
    found no match. Lives in-memory only (registered with persist=False)
    and is filtered out of the chip-list endpoint."""
    label = _humanise(class_name)
    return {
        "id": adhoc_scenario_id_for(case_id),
        "title": f"Ad-hoc · {ontology_id}.{class_name}",
        "domain": "Ad-hoc ontology lookups",
        "autonomous": True,
        "actor_id": "agent-data-lookup",
        "operator_role": {"label": "Operator", "name": "data.analyst"},
        "action_type": "ontology_lookup",
        "action_payload": {
            "ontology": ontology_id,
            "class": class_name,
            "where": where,
            "scope": "data.read",
        },
        "match_keywords": [],  # never re-classified
        "interpreted_as": purpose or f"ad-hoc lookup against {ontology_id}.{class_name}",
        "clarifying_question": (
            f"Routed via the ontology layer — no scenario matched, but "
            f"<code>{ontology_id}.{class_name}</code> covers this prompt. "
            f"Run a read-only autonomous lookup with where=<code>{where or '{}'}</code>?"
        ),
        "auto_approval_guardrail": "GR-ADHOC-LOOKUP",
        "auto_approval_reason": (
            "Read-only ontology lookup synthesized from the operator's prompt. "
            "Guardrail GR-ADHOC-LOOKUP permits autonomous ad-hoc reads."
        ),
        "closing_message": (
            f"Done — ad-hoc lookup against <code>{ontology_id}.{class_name}</code> "
            "completed. Per-fact provenance is on the audit trail."
        ),
        "stages": {
            "agent_intake": {
                "binder": "AdHocLookupAgentBinder/1.0",
                "facts": [
                    {
                        "source": "kf:graph",
                        "ontology_type": "Policy",
                        "id": "POL-ADHOC-LOOKUP",
                        "uri": "kf.tcs/policy/POL-ADHOC-LOOKUP",
                        "title": "Ad-hoc ontology lookup policy",
                        "payload": (
                            "Operator-initiated NL→ontology fallback lookups are "
                            "autonomous within the data.read scope when the "
                            "scenario classifier finds no match."
                        ),
                    },
                    {
                        "source": "iam:scopes",
                        "ontology_type": "ActorScope",
                        "id": "agent-data-lookup",
                        "uri": "iam.tcs/actors/agent-data-lookup",
                        "title": "Actor scope",
                        "payload": (
                            f"Scopes: data.read · ad-hoc lookup: "
                            f"{ontology_id}.{class_name} (routed from prompt)"
                        ),
                    },
                ],
            },
            "proposal": {
                "binder": "AdHocLookupProposalBinder/1.0",
                "ontology_queries": [
                    {
                        "ontology": ontology_id,
                        "class": class_name,
                        "where": where,
                        "purpose": purpose
                        or f"Ad-hoc ontology lookup from prompt: {prompt[:80]}",
                    }
                ],
            },
        },
        "outcomes": {
            "auto_execute": {
                "headline": (
                    f"Auto-executed — ad-hoc {class_name} fetched via {ontology_id}"
                ),
                "detail": (
                    f"Read-only NL→ontology lookup completed against "
                    f"{ontology_id}.{class_name}. Operator opted in to the "
                    "fallback for this prompt only; no chip was created."
                ),
            },
        },
        # Markers used by the registry / cases endpoints to recognise & hide
        # ad-hoc scenarios from the chip catalog.
        "_adhoc": True,
        "_custom_suggested_prompt": prompt[:80] if prompt else label,
    }
