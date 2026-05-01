"""Decides whether an action requires HITL review or auto-executes.

For now the policy is data-driven: the scenario YAML's `autonomous: true` flag
short-circuits review. In production this would read from a guardrail engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class PolicyDecision:
    mode: Literal["auto_approve", "requires_review"]
    guardrail_id: str = ""
    reason: str = ""


def evaluate(scenario: dict[str, Any]) -> PolicyDecision:
    if scenario.get("autonomous"):
        return PolicyDecision(
            mode="auto_approve",
            guardrail_id=scenario.get("auto_approval_guardrail", ""),
            reason=scenario.get("auto_approval_reason", ""),
        )
    return PolicyDecision(mode="requires_review")
