"""Supplier Assurance — the overarching orchestrator agent.

This module exposes the constants the orchestrator imports (agent id +
display name). The actual flow lives in `agent_orchestrator/orchestrator.py`
because it threads through the fabric client + narrator + SSE emitter,
which are run-scoped rather than agent-scoped.
"""
from __future__ import annotations

AGENT_ID = "supplier_assurance"
AGENT_NAME = "Supplier Assurance Orchestrator"
