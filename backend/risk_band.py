"""W4 / Beat 5 — dynamic authority recalculation.

A scenario marked ``autonomous: true`` declares an envelope under which
the agent may auto-execute (e.g. "auto-release POs under $10M"). For
the demo we want one case where the SAME scenario, fed a payload that
crosses the envelope, gets dynamically demoted to a HITL path. The
risk-band evaluator below is the pivot: it reads a scenario's optional
``risk_bands`` block, evaluates each band's predicate against the
drafted action's payload (and, optionally, against bound facts), and
returns the first matching band. The orchestrator then consults the
band's ``escalate_to`` directive to decide whether to override the
auto-execute branch.

YAML shape on a scenario::

    risk_bands:
      high:
        escalate_to: review_ready
        when:
          payload_field: po_value_usd
          op: gt
          threshold: 10_000_000
        reason: |-
          PO value exceeds the auto-release envelope of $10M.
          Escalating for human approval per GR-PP-AUTO-PO-002.

Supported ``op`` values: ``gt``, ``gte``, ``lt``, ``lte``, ``eq``,
``ne``. Threshold is compared with the field's float coercion;
non-numeric payload values fall through to "band did not match" (the
auto-execute branch continues normally).

Returning ``None`` means no band matched — the orchestrator proceeds
with the scenario's declared autonomy. Returning a dict means a band
matched; the orchestrator should honor ``escalate_to``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

_NUMERIC_OPS = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
}


def evaluate_risk_band(
    scenario: dict[str, Any],
    action_payload: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Evaluate the scenario's risk-band block against the action payload.

    Returns the matched band's info dict if any predicate fired, else
    ``None``. Iteration order matches YAML order — first match wins, so
    YAML authors should list the strictest band (e.g. ``high``) first.
    """
    bands = scenario.get("risk_bands") or {}
    if not isinstance(bands, dict) or not bands:
        return None
    for band_name, band_def in bands.items():
        if not isinstance(band_def, dict):
            continue
        when = band_def.get("when") or {}
        if not _matches(when, action_payload):
            continue
        return {
            "band": band_name,
            "escalate_to": band_def.get("escalate_to"),
            "reason": band_def.get("reason"),
            "matched_field": when.get("payload_field"),
            "matched_value": action_payload.get(when.get("payload_field")),
            "threshold": when.get("threshold"),
            "op": when.get("op"),
        }
    return None


def _matches(when: dict[str, Any], action_payload: dict[str, Any]) -> bool:
    field = when.get("payload_field")
    op = when.get("op")
    threshold = when.get("threshold")
    if not field or not op or threshold is None:
        return False
    raw = action_payload.get(field)
    if raw is None:
        return False
    comparator = _NUMERIC_OPS.get(op)
    if comparator is None:
        log.warning("risk_band: unsupported op %r", op)
        return False
    try:
        a = float(raw)
        b = float(threshold)
    except (TypeError, ValueError):
        return False
    return comparator(a, b)
