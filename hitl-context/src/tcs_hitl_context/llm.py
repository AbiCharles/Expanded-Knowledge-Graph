"""
LLM adapter — pluggable client used by the agent runtime.

Three implementations:
  * OpenAIClient       — public OpenAI API
  * AzureOpenAIClient  — Azure OpenAI deployment
  * FakeLLMClient      — canned responses for tests / demos without credentials

The adapter is intentionally minimal: a single async `complete` call that takes
a system + user message and returns the assistant's text. JSON-mode is opt-in
via `response_format="json"` so callers can request structured output.
"""
from __future__ import annotations

import json
import os
from typing import Any, Awaitable, Callable, Literal, Optional, Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """Pluggable LLM. All implementations are async."""

    name: str

    async def complete(
        self,
        *,
        system: str,
        user: str,
        response_format: Literal["text", "json"] = "text",
        temperature: float = 0.2,
    ) -> str:
        ...


# =============================================================================
# OpenAI (public API)
# =============================================================================
class OpenAIClient:
    name = "openai"

    def __init__(self, *, api_key: str, model: str):
        from openai import AsyncOpenAI  # imported lazily so framework users without openai don't pay
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def complete(
        self,
        *,
        system: str,
        user: str,
        response_format: Literal["text", "json"] = "text",
        temperature: float = 0.2,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}
        resp = await self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


# =============================================================================
# Azure OpenAI
# =============================================================================
class AzureOpenAIClient:
    name = "azure"

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        api_version: str,
        deployment: str,
    ):
        from openai import AsyncAzureOpenAI
        self._client = AsyncAzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint,
        )
        self._deployment = deployment

    async def complete(
        self,
        *,
        system: str,
        user: str,
        response_format: Literal["text", "json"] = "text",
        temperature: float = 0.2,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self._deployment,  # in Azure the "model" arg is the deployment name
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}
        resp = await self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


# =============================================================================
# Fake (tests / no-creds demo)
# =============================================================================
class FakeLLMClient:
    """Returns canned responses. Optionally drives different responses per call
    via the `responder` callback — `(system, user) -> str`. Default behaviour
    returns the user message back as a JSON `{"echo": ...}` payload."""

    name = "fake"

    def __init__(self, responder: Optional[Callable[[str, str], str]] = None):
        self._responder = responder

    async def complete(
        self,
        *,
        system: str,
        user: str,
        response_format: Literal["text", "json"] = "text",
        temperature: float = 0.2,
    ) -> str:
        if self._responder is not None:
            return self._responder(system, user)
        if response_format == "json":
            return json.dumps({"echo": user})
        return f"[fake response] {user[:120]}"


# =============================================================================
# Builder
# =============================================================================
def build_llm_client_from_env(env: Optional[dict[str, str]] = None) -> LLMClient:
    """Construct an LLMClient based on env vars.

    Reads:
      LLM_PROVIDER ∈ {openai, azure, fake}
      OpenAI:  OPENAI_API_KEY, OPENAI_MODEL
      Azure:   AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT,
               AZURE_OPENAI_API_VERSION, AZURE_OPENAI_DEPLOYMENT
    """
    e = env if env is not None else os.environ
    provider = (e.get("LLM_PROVIDER") or "fake").lower()
    if provider == "openai":
        key = e.get("OPENAI_API_KEY", "")
        if not key:
            raise RuntimeError("LLM_PROVIDER=openai but OPENAI_API_KEY is empty")
        return OpenAIClient(api_key=key, model=e.get("OPENAI_MODEL", "gpt-4o-mini"))
    if provider == "azure":
        for var in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"):
            if not e.get(var):
                raise RuntimeError(f"LLM_PROVIDER=azure but {var} is empty")
        return AzureOpenAIClient(
            api_key=e["AZURE_OPENAI_API_KEY"],
            endpoint=e["AZURE_OPENAI_ENDPOINT"],
            api_version=e.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            deployment=e["AZURE_OPENAI_DEPLOYMENT"],
        )
    if provider == "fake":
        return FakeLLMClient()
    raise RuntimeError(f"Unknown LLM_PROVIDER: {provider!r}. Expected one of: openai, azure, fake.")


__all__ = [
    "LLMClient",
    "OpenAIClient",
    "AzureOpenAIClient",
    "FakeLLMClient",
    "build_llm_client_from_env",
]
