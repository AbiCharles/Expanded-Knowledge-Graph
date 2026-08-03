"""Stitch several scenarios into one Outcome DAG ("compose then branch").

Given a question and an ordered list of scenario ids, this builds the graph
the frontend renders: the scenarios chain into a pipeline, and each
scenario's decision fans out into branches. A branch that *continues*
(``approve`` / ``auto_execute``) flows into the next scenario in the chain;
every other branch (``reject`` / ``request_more_info`` / an autonomy
escalation) spins off a terminal ``outcome``. The last scenario's branches
are all terminal. The result is a set of distinct root->outcome paths, each
a different combination of decisions across the stitched scenarios.

Autonomy is modelled faithfully: a scenario with ``autonomous: true`` and a
``risk_bands`` block first hits an **authority gate** (``auto_execute`` vs
an escalation to human review); the escalation leads to a nested HITL
decision. That two-level structure is exactly what produces "several
different paths to the same kind of outcome".

Branch weights come from `probability.branch_distribution` (author ->
history -> default), optionally nudged by an ontology reliability score.
History is injected as a callable so this module needs no DB.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from .outcome_plan import OutcomeEdge, OutcomeNode, OutcomePlan
from .probability import (
    CONTINUE_KINDS,
    HITL_DEFAULTS,
    HITL_KINDS,
    apply_reliability,
    author_overrides_for,
    branch_distribution,
    compute_outcomes,
)
from .risk_band import evaluate_risk_band

# scenario_id -> {decision_kind: count}. Returns {} when there's no history.
HistoryProvider = Callable[[str], dict[str, float]]

_ACCENT_BY_OUTCOME = {
    "approve": "",
    "auto_execute": "",
    "reject": "risk",
    "request_more_info": "risk_path",
    "review_ready": "alt",
}


def _basis_rationale(basis: str, kind: str, history: dict[str, float]) -> str:
    if basis == "author":
        return "Author-set weight"
    if basis == "history":
        n = int(history.get(kind, 0))
        total = int(sum(history.values()))
        return f"{n}/{total} past cases resolved '{kind}'" if total else "Historical prior"
    if basis == "agent":
        return "Agent-refined"
    return "Default prior"


class _Builder:
    """Mutable accumulator for nodes/edges with stable, unique ids."""

    def __init__(self) -> None:
        self.nodes: list[OutcomeNode] = []
        self.edges: list[OutcomeEdge] = []
        self._n = 0
        self._e = 0

    def node(self, kind: str, label: str, **kw: Any) -> str:
        nid = f"n{self._n}"
        self._n += 1
        self.nodes.append(OutcomeNode(id=nid, kind=kind, label=label, **kw))
        return nid

    def edge(
        self, source: str, target: str, probability: float, *, label: str = "",
        basis: str = "structural", rationale: str = "", accent: str = "",
    ) -> str:
        eid = f"e{self._e}"
        self._e += 1
        self.edges.append(
            OutcomeEdge(
                id=eid, source=source, target=target, label=label,
                probability=round(float(probability), 6), basis=basis,
                rationale=rationale, accent=accent,
            )
        )
        return eid


def _reliability_for(scenario: dict, context: dict) -> Optional[float]:
    """Pull a reliability score for this scenario's subject from context.

    Accepts either a per-scenario map or a single global value:
        {"reliability_by_scenario": {"SC-...": 0.8}}  or  {"reliability_score": 0.8}
    """
    by_scn = context.get("reliability_by_scenario")
    if isinstance(by_scn, dict):
        val = by_scn.get(scenario.get("id"))
        if isinstance(val, (int, float)):
            return float(val)
    val = context.get("reliability_score")
    return float(val) if isinstance(val, (int, float)) else None


def _distribution(
    scenario: dict, kinds: list[str], history: dict[str, float],
    defaults: dict[str, float], context: dict,
) -> tuple[dict[str, float], dict[str, str]]:
    dist, basis = branch_distribution(
        kinds,
        history_counts=history,
        author_overrides=author_overrides_for(scenario),
        defaults=defaults,
    )
    dist = apply_reliability(dist, _reliability_for(scenario, context))
    return dist, basis


def _outcome_label(scenario: dict, kind: str) -> str:
    outcomes = scenario.get("outcomes")
    if isinstance(outcomes, dict):
        meta = outcomes.get(kind)
        if isinstance(meta, dict) and meta.get("headline"):
            return str(meta["headline"])
    title = scenario.get("title", scenario.get("id", "scenario"))
    return f"{kind} — {title}"


def compose(
    question: str,
    scenario_ids: list[str],
    *,
    scenarios: Any,
    history_provider: Optional[HistoryProvider] = None,
    context: Optional[dict] = None,
) -> OutcomePlan:
    """Build and weight the Outcome DAG. Raises KeyError on unknown id."""
    context = context or {}
    history_provider = history_provider or (lambda _sid: {})
    b = _Builder()

    root = b.node("question", question or "Question", accent="anchor")
    # Pending "continue" exits to wire into the NEXT scenario's step node.
    # Each: (source_node_id, decision_label, edge_probability, basis, rationale).
    exits: list[tuple[str, str, float, str, str]] = [(root, "start", 1.0, "structural", "")]

    last = len(scenario_ids) - 1
    for i, sid in enumerate(scenario_ids):
        scenario = scenarios.require(sid)
        raw_history = {str(k): float(v) for k, v in (history_provider(sid) or {}).items()}
        outcomes_meta = scenario.get("outcomes") if isinstance(scenario.get("outcomes"), dict) else {}
        is_last = i == last

        step = b.node(
            "scenario_step", scenario.get("title", sid),
            scenario_id=sid, step_index=i + 1,
        )
        for src, label, prob, basis, rationale in exits:
            b.edge(src, step, prob, label=label, basis=basis, rationale=rationale)
        exits = []

        autonomous = bool(scenario.get("autonomous")) and bool(scenario.get("risk_bands"))

        def _emit_branches(
            decision_node: str, kinds: list[str], dist: dict[str, float],
            basis_map: dict[str, str], history: dict[str, float],
        ) -> None:
            """Turn a decision's branches into continue-exits or terminals."""
            for kind in kinds:
                prob = dist[kind]
                basis = basis_map.get(kind, "default")
                rationale = _basis_rationale(basis, kind, history)
                accent = _ACCENT_BY_OUTCOME.get(kind, "")
                if kind in CONTINUE_KINDS and not is_last:
                    exits.append((decision_node, kind, prob, basis, rationale))
                else:
                    outcome = b.node(
                        "outcome", _outcome_label(scenario, kind),
                        scenario_id=sid, outcome_kind=kind, accent=accent,
                    )
                    b.edge(
                        decision_node, outcome, prob, label=kind, basis=basis,
                        rationale=rationale, accent="risk_path" if accent in ("risk", "risk_path") else "",
                    )

        if autonomous:
            gate = b.node("decision", "Authority gate", scenario_id=sid, step_index=i + 1)
            b.edge(step, gate, 1.0, label="proposal", basis="structural")

            gate_kinds = [k for k in ("auto_execute", "review_ready") if k in outcomes_meta] \
                or ["auto_execute", "review_ready"]
            # Gate history: auto_execute vs "escalated" (any HITL decision the
            # scenario ever recorded — those are cases that crossed the band).
            gate_history = {
                "auto_execute": raw_history.get("auto_execute", 0.0),
                "review_ready": sum(raw_history.get(k, 0.0) for k in HITL_KINDS),
            }
            band_hit = evaluate_risk_band(scenario, scenario.get("action_payload") or {})
            gate_defaults = (
                {"auto_execute": 0.15, "review_ready": 0.85} if band_hit
                else {"auto_execute": 0.85, "review_ready": 0.15}
            )
            gate_dist, gate_basis = _distribution(
                scenario, gate_kinds, gate_history, gate_defaults, context
            )

            # auto_execute -> continue/terminal
            if "auto_execute" in gate_kinds:
                prob = gate_dist["auto_execute"]
                basis = gate_basis.get("auto_execute", "default")
                rationale = _basis_rationale(basis, "auto_execute", gate_history)
                if not is_last:
                    exits.append((gate, "auto_execute", prob, basis, rationale))
                else:
                    outcome = b.node(
                        "outcome", _outcome_label(scenario, "auto_execute"),
                        scenario_id=sid, outcome_kind="auto_execute",
                    )
                    b.edge(gate, outcome, prob, label="auto_execute", basis=basis, rationale=rationale)

            # review_ready -> nested HITL decision
            if "review_ready" in gate_kinds:
                esc_prob = gate_dist["review_ready"]
                esc_basis = gate_basis.get("review_ready", "default")
                hitl = b.node("decision", "Escalated review", scenario_id=sid, step_index=i + 1)
                b.edge(
                    gate, hitl, esc_prob, label="review_ready", basis=esc_basis,
                    rationale=_basis_rationale(esc_basis, "review_ready", gate_history),
                    accent="risk_path",
                )
                hitl_kinds = [k for k in HITL_KINDS if k in outcomes_meta] or list(HITL_KINDS)
                hitl_hist = {k: raw_history.get(k, 0.0) for k in hitl_kinds}
                hitl_dist, hitl_basis = _distribution(
                    scenario, hitl_kinds, hitl_hist, HITL_DEFAULTS, context
                )
                _emit_branches(hitl, hitl_kinds, hitl_dist, hitl_basis, hitl_hist)
        else:
            decision = b.node("decision", "Reviewer decision", scenario_id=sid, step_index=i + 1)
            b.edge(step, decision, 1.0, label="proposal", basis="structural")
            kinds = [k for k in HITL_KINDS if k in outcomes_meta] or list(HITL_KINDS)
            history = {k: raw_history.get(k, 0.0) for k in kinds}
            dist, basis_map = _distribution(scenario, kinds, history, HITL_DEFAULTS, context)
            _emit_branches(decision, kinds, dist, basis_map, history)

    # Any continue-exits left after the last scenario become terminal outcomes.
    for src, label, prob, basis, rationale in exits:
        scenario = scenarios.require(scenario_ids[-1])
        outcome = b.node(
            "outcome", _outcome_label(scenario, label),
            scenario_id=scenario_ids[-1], outcome_kind=label,
        )
        b.edge(src, outcome, prob, label=label, basis=basis, rationale=rationale)

    plan = OutcomePlan(question=question, scenario_ids=list(scenario_ids), nodes=b.nodes, edges=b.edges)
    summaries, stats = compute_outcomes(plan.nodes, plan.edges)
    plan.outcomes = summaries
    plan.stats = {"nodes": float(len(plan.nodes)), "edges": float(len(plan.edges)), **stats}
    return plan
