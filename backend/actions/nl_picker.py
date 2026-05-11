"""Natural-language → action picker.

Given a prompt and the registered action catalog, ask the LLM to pick
the closest action and extract its arguments. Falls back to keyword
matching against `match_keywords` when LLM credentials are missing,
which only handles simple cases — but enough to drive the demo without
a key.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from .loader import ActionRegistry
from .models import Action, NLActionMatch

log = logging.getLogger(__name__)


class NLActionParseError(Exception):
    """Raised when neither the LLM nor the fallback could pick an action."""


_PICK_SYSTEM = """You translate a natural-language operator request into a
structured write-action call.

Input you receive:
  - the operator's prompt
  - a catalog of available actions with their typed argument schemas

Output strict JSON only, matching this schema:
{
  "action_id": string|null,        // exactly one id from the catalog, or null
  "arguments": { "<arg>": <value>, ... },   // values typed per the schema
  "confidence": float,             // 0.0-1.0
  "rationale": string              // 1 short sentence
}

Rules:
  - "action_id" must be one of the catalog action ids, exactly. null if
    no action fits.
  - Every required argument must be present in "arguments" or you must
    return action_id=null with a rationale that names the missing field.
  - Numeric arguments must be JSON numbers, not strings.
  - Do not invent argument keys not declared on the chosen action."""


async def parse_nl_action(
    prompt: str, registry: ActionRegistry, llm: Any
) -> NLActionMatch:
    """Return the best NLActionMatch for `prompt`.

    Raises NLActionParseError when nothing matches (LLM returned null,
    or required arguments couldn't be filled, or fallback found no
    keyword overlap)."""
    prompt = (prompt or "").strip()
    if not prompt:
        raise NLActionParseError("empty prompt")
    if not registry.all():
        raise NLActionParseError("no actions registered")

    use_llm = getattr(llm, "name", "fake") not in ("fake", "")
    if use_llm:
        try:
            parsed = await _llm_pick(prompt, registry, llm)
        except Exception as exc:  # noqa: BLE001
            log.warning("LLM action-pick fell back: %s", exc)
            parsed = _fallback_pick(prompt, registry)
    else:
        parsed = _fallback_pick(prompt, registry)

    action_id = parsed.get("action_id")
    if not action_id:
        raise NLActionParseError(
            parsed.get("rationale") or "no action matched the prompt"
        )
    action = registry.get(action_id)
    if action is None:
        raise NLActionParseError(
            f"picker proposed unknown action {action_id!r}; "
            f"registry has: {registry.ids()}"
        )

    args = _coerce_args(parsed.get("arguments") or {}, action)
    missing = [a.name for a in action.arguments if a.required and a.name not in args]
    if missing:
        raise NLActionParseError(
            f"action {action_id!r} requires {missing} but the prompt didn't supply them"
        )

    return NLActionMatch(
        action_id=action_id,
        arguments=args,
        confidence=float(parsed.get("confidence") or 0.0),
        rationale=str(parsed.get("rationale") or ""),
    )


# =============================================================================
# LLM
# =============================================================================
async def _llm_pick(
    prompt: str, registry: ActionRegistry, llm: Any
) -> dict[str, Any]:
    catalog_lines = []
    for a in registry.all():
        arg_descs = ", ".join(
            f"{arg.name}:{arg.type}"
            + (" (required)" if arg.required else "")
            + (f" e.g. {arg.example!r}" if arg.example else "")
            for arg in a.arguments
        )
        catalog_lines.append(
            f"  - {a.id}: {a.title}\n"
            f"      description: {a.description or '(none)'}\n"
            f"      arguments: {arg_descs or '(none)'}"
        )
    user_msg = (
        "Action catalog:\n"
        + "\n".join(catalog_lines)
        + f"\n\nOperator prompt: {prompt!r}\n\n"
        + "Return JSON only."
    )
    raw = await llm.complete(
        system=_PICK_SYSTEM, user=user_msg, response_format="json", temperature=0.1,
    )
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("LLM response was not a JSON object")
    return parsed


# =============================================================================
# Fallback picker (keyword match)
# =============================================================================
def _fallback_pick(prompt: str, registry: ActionRegistry) -> dict[str, Any]:
    lower = prompt.lower()
    scored: list[tuple[int, Action]] = []
    for a in registry.all():
        score = sum(1 for kw in a.match_keywords if kw.lower() in lower)
        if score > 0:
            scored.append((score, a))
    if not scored:
        return {
            "action_id": None,
            "arguments": {},
            "confidence": 0.0,
            "rationale": (
                "no action's match_keywords appeared in the prompt; "
                "configure an LLM (set OPENAI_API_KEY) for richer picking"
            ),
        }
    scored.sort(key=lambda t: -t[0])
    chosen = scored[0][1]
    # The fallback can't extract typed arguments. If the action requires
    # args, we still return the pick + a rationale; the caller will
    # raise on missing required args.
    return {
        "action_id": chosen.id,
        "arguments": _extract_simple_args(prompt, chosen),
        "confidence": 0.5,
        "rationale": (
            f"keyword-fallback matched {chosen.id!r}; argument extraction "
            "is limited (LLM does this properly)"
        ),
    }


_TOKEN_ID = re.compile(r"\b[A-Z][A-Z0-9_-]*[A-Z0-9]\b")
_INT_RE = re.compile(r"-?\b\d+\b")


def _extract_simple_args(prompt: str, action: Action) -> dict[str, Any]:
    """Best-effort extraction without an LLM. Strings are pulled from
    UPPERCASE-LIKE tokens (e.g. SKU-EL-2210); integers from digit runs."""
    out: dict[str, Any] = {}
    upper_tokens = _TOKEN_ID.findall(prompt)
    int_tokens = _INT_RE.findall(prompt)
    int_idx = 0
    upper_idx = 0
    for arg in action.arguments:
        if arg.type == "integer":
            if int_idx < len(int_tokens):
                out[arg.name] = int(int_tokens[int_idx])
                int_idx += 1
        elif arg.type == "decimal":
            if int_idx < len(int_tokens):
                out[arg.name] = float(int_tokens[int_idx])
                int_idx += 1
        elif arg.type == "boolean":
            out[arg.name] = "true" in prompt.lower() or "yes" in prompt.lower()
        elif arg.type == "string" and arg.name.endswith("_id"):
            if upper_idx < len(upper_tokens):
                out[arg.name] = upper_tokens[upper_idx]
                upper_idx += 1
    return out


# =============================================================================
# Coercion (post-LLM)
# =============================================================================
def _coerce_args(raw: dict[str, Any], action: Action) -> dict[str, Any]:
    """Coerce LLM string outputs to the declared types (LLMs sometimes
    return numbers as strings)."""
    out: dict[str, Any] = {}
    name_to_type = {a.name: a.type for a in action.arguments}
    for k, v in raw.items():
        if k not in name_to_type:
            continue  # drop unknown keys defensively
        t = name_to_type[k]
        try:
            if t == "integer":
                out[k] = int(v) if not isinstance(v, bool) else int(v)
            elif t == "decimal":
                out[k] = float(v)
            elif t == "boolean":
                out[k] = bool(v) if isinstance(v, bool) else str(v).lower() in ("true", "1", "yes")
            else:
                out[k] = v if isinstance(v, str) else json.dumps(v)
        except (ValueError, TypeError):
            # Skip un-coercible values; required-arg check downstream will
            # surface the gap.
            continue
    return out


# =============================================================================
# __init__.py exports
# =============================================================================
def get_optional(action_id: Optional[str], registry: ActionRegistry) -> Optional[Action]:
    if not action_id:
        return None
    return registry.get(action_id)
