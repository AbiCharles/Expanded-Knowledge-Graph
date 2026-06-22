"""Short LLM narration for the agent flow.

Wraps `tcs_hitl_context.llm.build_llm_client_from_env()`. The
investigation steps are scripted in Python (deterministic for demo
day), but between steps we ask the LLM for a 1–2 sentence "agent
thinking" line so the audience feels the reasoning.

Falls back to a canned line if the LLM call fails — the demo never
stalls on an LLM outage.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger(__name__)


class Narrator:
    """LLM-backed narration helper. One client per orchestrator run."""

    def __init__(self) -> None:
        self._client = None
        self._init_error: Optional[str] = None
        try:
            from tcs_hitl_context import build_llm_client_from_env

            env = {
                "LLM_PROVIDER": os.environ.get("LLM_PROVIDER", "fake"),
                "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
                "OPENAI_MODEL": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                "AZURE_OPENAI_API_KEY": os.environ.get("AZURE_OPENAI_API_KEY", ""),
                "AZURE_OPENAI_ENDPOINT": os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
                "AZURE_OPENAI_API_VERSION": os.environ.get(
                    "AZURE_OPENAI_API_VERSION", "2024-10-21"
                ),
                "AZURE_OPENAI_DEPLOYMENT": os.environ.get(
                    "AZURE_OPENAI_DEPLOYMENT", ""
                ),
            }
            self._client = build_llm_client_from_env(env)
        except Exception as exc:  # noqa: BLE001
            self._init_error = str(exc)
            log.warning("Narrator falling back to canned lines: %s", exc)

    async def narrate(
        self,
        *,
        agent_name: str,
        finding: str,
        fallback: str,
    ) -> str:
        """Return a 1–2 sentence narration of what the agent is thinking.

        `finding` is a terse fact sentence the orchestrator just learned
        (e.g. "Three tier-1 buyers source from SUP-021: Hemlock, Granite,
        Crimson."). `fallback` is the canned line used when the LLM is
        unavailable — should already read well by itself so demos still
        work without an LLM key.
        """
        if self._client is None or getattr(self._client, "name", "fake") == "fake":
            return fallback
        system = (
            f"You are {agent_name}, an investigative agent running inside a "
            f"supply-assurance orchestrator. Narrate ONE internal thought in "
            f"1–2 sentences, present tense, no quotes. Stay factual and "
            f"reference the finding directly; do not invent details. Plain "
            f"text only, no markdown."
        )
        try:
            text = await self._client.complete(
                system=system,
                user=f"Finding just received:\n{finding}",
                response_format="text",
                temperature=0.3,
            )
            text = (text or "").strip()
            return text or fallback
        except Exception as exc:  # noqa: BLE001
            log.warning("narrate() failed; using fallback: %s", exc)
            return fallback
