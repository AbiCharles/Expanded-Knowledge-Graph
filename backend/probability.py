"""Hybrid probability model for the Outcome DAG.

Where do the branch probabilities come from? Three sources, blended in
priority order (this is the "hybrid" the feature calls for):

  1. **Author** — a scenario YAML may pin weights, either as a top-level
     ``branch_probabilities:`` map or a per-outcome ``probability:`` under
     the existing ``outcomes:`` block. Author values win.
  2. **History** — otherwise, seed from how the scenario's own past cases
     actually resolved: the frequency of each ``decision_kind`` in the
     ``cases`` table (the same denominator `api/insights.py` uses for
     ``share_of_decisions``). Laplace-smoothed so a never-seen branch still
     gets a sliver.
  3. **Default** — otherwise a sensible prior (risk-band-aware for the
     autonomy gate; a mild approve-lean for HITL review).

On top of that, an optional ontology **reliability_score** for the
scenario's subject supplier nudges the approve/reject split, and an
optional **agent** pass can refine the distribution given the specific
question. Everything is renormalised so sibling branches always sum to 1.

Pure functions, no I/O — the caller injects history counts — so this is
trivially unit-testable.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

# The three HITL reviewer choices (order = display order).
HITL_KINDS = ("approve", "reject", "request_more_info")
# Decisions that let a composed pipeline PROCEED to the next scenario
# rather than terminate in an outcome.
CONTINUE_KINDS = frozenset({"approve", "auto_execute"})
# Mild priors used only when there's neither an author weight nor history.
HITL_DEFAULTS = {"approve": 0.6, "reject": 0.25, "request_more_info": 0.15}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    """Scale non-negative weights to sum to 1; uniform if all zero/empty."""
    positive = {k: max(0.0, float(v)) for k, v in weights.items()}
    total = sum(positive.values())
    if total <= 0.0:
        n = len(positive) or 1
        return {k: 1.0 / n for k in positive}
    return {k: v / total for k, v in positive.items()}


def branch_distribution(
    kinds: Iterable[str],
    *,
    history_counts: Optional[dict[str, float]] = None,
    author_overrides: Optional[dict[str, float]] = None,
    defaults: Optional[dict[str, float]] = None,
    alpha: float = 1.0,
) -> tuple[dict[str, float], dict[str, str]]:
    """Return ``(distribution, basis)`` over ``kinds``.

    ``distribution`` sums to 1; ``basis[kind]`` is one of
    "author"|"history"|"default" explaining that branch's weight.

    Author overrides are honoured for the kinds they name; the leftover
    probability mass is spread over the remaining kinds by history share
    (or defaults, or uniform). With no author input the whole distribution
    is history (Laplace-smoothed) if any history exists, else defaults,
    else uniform.
    """
    kinds = list(dict.fromkeys(kinds))  # de-dupe, keep order
    if not kinds:
        return {}, {}
    history_counts = history_counts or {}
    author_overrides = author_overrides or {}
    defaults = defaults or {}
    basis: dict[str, str] = {}

    authored = {
        k: _clamp(float(author_overrides[k])) for k in kinds if k in author_overrides
    }
    if authored:
        weights: dict[str, float] = {}
        remaining = [k for k in kinds if k not in authored]
        leftover = max(0.0, 1.0 - sum(authored.values()))
        if remaining:
            hist = {k: float(history_counts.get(k, 0.0)) for k in remaining}
            if sum(hist.values()) > 0:
                share = _normalize({k: hist[k] + alpha for k in remaining})
                src = "history"
            elif any(defaults.get(k, 0.0) for k in remaining):
                share = _normalize({k: float(defaults.get(k, 0.0)) for k in remaining})
                src = "default"
            else:
                share = {k: 1.0 / len(remaining) for k in remaining}
                src = "default"
            for k in remaining:
                weights[k] = leftover * share[k]
                basis[k] = src
        for k, v in authored.items():
            weights[k] = v
            basis[k] = "author"
        return _normalize(weights), basis

    hist = {k: float(history_counts.get(k, 0.0)) for k in kinds}
    if sum(hist.values()) > 0:
        for k in kinds:
            basis[k] = "history"
        return _normalize({k: hist[k] + alpha for k in kinds}), basis

    if any(defaults.get(k, 0.0) for k in kinds):
        for k in kinds:
            basis[k] = "default"
        return _normalize({k: float(defaults.get(k, 0.0)) for k in kinds}), basis

    for k in kinds:
        basis[k] = "default"
    return {k: 1.0 / len(kinds) for k in kinds}, basis


def apply_reliability(
    distribution: dict[str, float],
    reliability: Optional[float],
    *,
    max_shift: float = 0.2,
) -> dict[str, float]:
    """Bias approve<->reject by an ontology reliability score in [0, 1].

    reliability > 0.5 shifts mass from reject to approve (a dependable
    supplier is more likely to be approved); < 0.5 the other way. The shift
    is bounded by ``max_shift`` and the result renormalised. No-op unless
    both "approve" and "reject" are present.
    """
    if reliability is None or "approve" not in distribution or "reject" not in distribution:
        return distribution
    shifted = dict(distribution)
    shift = _clamp((float(reliability) - 0.5) * 2.0 * max_shift, -max_shift, max_shift)
    shifted["approve"] = _clamp(shifted["approve"] + shift, 0.01, 0.99)
    shifted["reject"] = _clamp(shifted["reject"] - shift, 0.01, 0.99)
    return _normalize(shifted)


def author_overrides_for(scenario: dict) -> dict[str, float]:
    """Pull author-pinned branch weights out of a (loose-shape) scenario.

    Two accepted forms, per-outcome winning over the top-level map:
        branch_probabilities: {approve: 0.7, reject: 0.3}
        outcomes: {approve: {probability: 0.7, ...}, ...}
    """
    out: dict[str, float] = {}
    bp = scenario.get("branch_probabilities")
    if isinstance(bp, dict):
        for k, v in bp.items():
            if isinstance(v, (int, float)):
                out[str(k)] = float(v)
    outcomes = scenario.get("outcomes")
    if isinstance(outcomes, dict):
        for k, meta in outcomes.items():
            if isinstance(meta, dict) and isinstance(meta.get("probability"), (int, float)):
                out[str(k)] = float(meta["probability"])
    return out


def compute_outcomes(nodes: list, edges: list, *, max_paths: int = 20000):
    """Walk the DAG root->terminals; fill outcome node probabilities.

    Returns ``(summaries, stats)``. Mutates each ``outcome`` node's
    ``probability`` in place. ``summaries`` is a list of ``OutcomeSummary``
    sorted most-probable first. Enumerates every distinct path (a composed
    DAG terminal can be reachable by several), aggregating probability per
    terminal node. ``max_paths`` is a defensive cap against pathological
    fan-out.
    """
    # Imported here to avoid a circular import at module load.
    from .outcome_plan import OutcomeSummary

    adjacency: dict[str, list] = defaultdict(list)
    for e in edges:
        adjacency[e.source].append(e)
    node_by_id = {n.id: n for n in nodes}

    targets = {e.target for e in edges}
    roots = [n for n in nodes if n.kind == "question"] or [
        n for n in nodes if n.id not in targets
    ]

    paths: list[tuple[str, float, list[str]]] = []  # (outcome_id, prob, edge_ids)
    truncated = False

    def _walk(node_id: str, prob: float, trail: list[str]) -> None:
        nonlocal truncated
        if len(paths) >= max_paths:
            truncated = True
            return
        node = node_by_id.get(node_id)
        outgoing = adjacency.get(node_id, [])
        if node is not None and node.kind == "outcome":
            paths.append((node_id, prob, list(trail)))
            return
        if not outgoing:
            return
        for edge in outgoing:
            trail.append(edge.id)
            _walk(edge.target, prob * float(edge.probability), trail)
            trail.pop()

    for root in roots:
        _walk(root.id, 1.0, [])

    agg: dict[str, dict] = defaultdict(lambda: {"prob": 0.0, "paths": []})
    for outcome_id, prob, trail in paths:
        agg[outcome_id]["prob"] += prob
        agg[outcome_id]["paths"].append(trail)

    summaries = []
    for outcome_id, info in agg.items():
        node = node_by_id[outcome_id]
        node.probability = round(info["prob"], 6)
        summaries.append(
            OutcomeSummary(
                id=outcome_id,
                label=node.label,
                outcome_kind=node.outcome_kind,
                scenario_id=node.scenario_id,
                probability=round(info["prob"], 6),
                path_edge_ids=info["paths"],
            )
        )
    summaries.sort(key=lambda o: o.probability, reverse=True)
    stats = {
        "outcomes": float(len(summaries)),
        "paths": float(len(paths)),
        "total_probability": round(sum(o.probability for o in summaries), 6),
        "truncated": 1.0 if truncated else 0.0,
    }
    return summaries, stats
