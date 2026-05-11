"""Natural-language → OntologyQuery parser.

Given a prompt like "show suppliers in NL with reliability < 0.5" plus
the ontology document, ask the LLM to pick the class and produce a
structured `OntologyQuery`. Falls back to a deterministic keyword
matcher when the LLM is unavailable so the playground still works
without credentials (the fallback only handles the simplest case —
class name + literal attribute equality — and returns a clear error
otherwise).

Phase 3 scope:
  - LLM emits a class + filter dict
  - Fallback: string-match the prompt against class names + attribute names
  - No relation traversal yet (`include_relations` always empty)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from .models import Mapping, Ontology, OntologyQuery

log = logging.getLogger(__name__)


class NLParseError(Exception):
    """Raised when neither the LLM nor the fallback can produce a query."""


_NL_SYSTEM = """You translate a natural-language data question into a structured
ontology query.

Input you receive:
  - the operator's prompt
  - the ontology id + a list of classes with their attributes

Output strict JSON only, matching this schema:
{
  "class": string,                 // exactly one class name from the ontology
  "where": { "<attr>": <value>, ... },  // attribute filters (literal values,
                                         //   or {"<": n} / {">": n} for numeric
                                         //   comparisons; empty {} means no filter)
  "max_results": integer,          // 1..200, default 50
  "purpose": string                // 1 short sentence describing the query
}

Rules:
  - "class" must be one of the listed class names exactly (case-sensitive)
  - "where" keys must be attributes declared on that class
  - If you cannot confidently map the prompt to a class, output
    {"class": null, "where": {}, "max_results": 50, "purpose": "<reason>"}"""


async def parse_nl_query(
    prompt: str,
    ontology: Ontology,
    llm: Any,
    *,
    attribute_samples: Optional[dict[str, dict[str, list]]] = None,
) -> OntologyQuery:
    """Return a structured OntologyQuery for the given prompt.

    Always uses the LLM when one is configured. Falls back to a
    deterministic name-matcher when `llm.name == 'fake'` so the demo
    works without credentials.

    `attribute_samples` (optional, shape `{class: {attr: [samples]}}`)
    is rendered into the LLM prompt so it can normalize human-readable
    filter values to the actual data shape — e.g. *"Dutch suppliers"*
    → `country: "NL"` instead of `country: "Dutch"` when the sample
    values include `NL`. Use `collect_attribute_samples()` to build it
    from the active mapping + data sources.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise NLParseError("empty prompt")

    use_llm = getattr(llm, "name", "fake") not in ("fake", "")
    if use_llm:
        try:
            parsed = await _llm_parse(
                prompt, ontology, llm, attribute_samples=attribute_samples
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("NL parse fell back from LLM: %s", exc)
            parsed = _fallback_parse(prompt, ontology)
    else:
        parsed = _fallback_parse(prompt, ontology)

    cls_name = parsed.get("class")
    if not cls_name:
        raise NLParseError(
            parsed.get("purpose")
            or "could not map prompt to any ontology class"
        )
    if cls_name not in ontology.classes:
        raise NLParseError(
            f"parser proposed unknown class {cls_name!r}; "
            f"ontology has: {list(ontology.classes)}"
        )

    return OntologyQuery(
        ontology=ontology.id,
        **{"class": cls_name},
        where=parsed.get("where") or {},
        include_relations=[],
        max_results=int(parsed.get("max_results") or 50),
        purpose=parsed.get("purpose") or f"NL query: {prompt[:80]}",
    )


# =============================================================================
# LLM path
# =============================================================================
async def _llm_parse(
    prompt: str,
    ontology: Ontology,
    llm: Any,
    *,
    attribute_samples: Optional[dict[str, dict[str, list]]] = None,
) -> dict[str, Any]:
    samples = attribute_samples or {}

    def _attr_block(class_name: str, attr) -> str:
        base = f"{attr.name}:{attr.type}"
        cls_samples = samples.get(class_name, {})
        sv = cls_samples.get(attr.name, [])
        if sv:
            preview = ", ".join(repr(s) for s in list(sv)[:5])
            base += f" [data sample values: {preview}]"
        return base

    classes_block = "\n".join(
        f"  - {name} (attributes: "
        + ", ".join(_attr_block(name, a) for a in cls.attributes)
        + ")"
        for name, cls in ontology.classes.items()
    )
    user_msg = (
        f"Ontology id: {ontology.id}\n"
        f"Classes:\n{classes_block}\n\n"
        f"Prompt: {prompt!r}\n\n"
        "When the prompt names a filter value in human form (e.g. 'Dutch'),\n"
        "use the data-sample values shown above to pick the form the data\n"
        "actually uses (e.g. 'NL') rather than the human-readable form.\n"
        "Return JSON only."
    )
    raw = await llm.complete(
        system=_NL_SYSTEM, user=user_msg, response_format="json", temperature=0.1,
    )
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("LLM response was not a JSON object")
    return parsed


# =============================================================================
# Deterministic fallback
# =============================================================================
def collect_attribute_samples(
    ontology: Ontology,
    mapping: Optional[Mapping],
    data_sources,
    *,
    max_per_attr: int = 5,
) -> dict[str, dict[str, list]]:
    """Walk the mapping → source schemas → return per-class per-attribute
    sample values for the LLM prompt.

    Returned shape: `{class_name: {attribute_name: [samples...]}}`.
    Empty when no mapping, missing source, or schema introspection
    yields nothing (e.g. HTTP/vector). Cheap to call but does open
    transient connections — caller should pass the result, not call
    once per question if perf matters.
    """
    out: dict[str, dict[str, list]] = {}
    if mapping is None:
        return out
    # Local import to avoid a cycle (schema_introspect imports DataSourceRegistry,
    # this module is imported by api/cases.py which already imports state.py).
    from .schema_introspect import inspect_source

    # Cache schema-per-source so a binding referencing the same source twice
    # only inspects once.
    schema_cache: dict[str, dict[str, list]] = {}

    def _samples_for(source_id: str) -> dict[str, list]:
        if source_id in schema_cache:
            return schema_cache[source_id]
        spec = data_sources._specs.get(source_id)  # type: ignore[attr-defined]
        if spec is None:
            schema_cache[source_id] = {}
            return {}
        try:
            schema = inspect_source(spec, data_sources)
        except Exception as exc:  # noqa: BLE001
            log.info("samples: inspect %s failed (%s)", source_id, exc)
            schema_cache[source_id] = {}
            return {}
        cols: dict[str, list] = {}
        for table in schema.tables:
            for col in table.columns:
                # First-table-wins is fine — the binding's attribute_map
                # points at one specific column name regardless of which
                # table it lives in.
                if col.name not in cols and col.sample_values:
                    cols[col.name] = list(col.sample_values)
        schema_cache[source_id] = cols
        return cols

    for class_name, class_mapping in mapping.mappings.items():
        per_attr: dict[str, list] = {}
        for binding in class_mapping.sources:
            cols = _samples_for(binding.data_source)
            for attr, col in binding.attribute_map.items():
                if attr in per_attr:
                    continue  # first binding wins
                samples = cols.get(col)
                if samples:
                    per_attr[attr] = samples[:max_per_attr]
        if per_attr:
            out[class_name] = per_attr
    return out


_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")


def _norm(s: str) -> str:
    """Lowercase and collapse non-alnum runs to single spaces."""
    return _NON_ALNUM.sub(" ", (s or "").lower()).strip()


def _norm_class(name: str) -> str:
    """Same as _norm but splits camelCase first so `PurchaseOrder`
    matches a prompt that says `purchase order(s)`."""
    return _norm(_CAMEL_BOUNDARY.sub(r"\1 \2", name or ""))


def _fallback_parse(prompt: str, ontology: Ontology) -> dict[str, Any]:
    """Pick a class by name occurrence in the prompt.

    Doesn't do attribute filters — too brittle without an LLM. Returns
    `class=None` if no class name appears.
    """
    norm_prompt = " " + _norm(prompt) + " "
    candidates: list[tuple[int, str]] = []
    for name in ontology.classes:
        n = _norm_class(name)
        if not n:
            continue
        # Match singular, naive plural, or the un-split form so authors who
        # wrote `PurchaseOrder` and operators who type `purchaseorder` both win.
        forms = {n, f"{n}s", _norm(name)}
        for form in forms:
            if f" {form} " in norm_prompt:
                # Score by number of words matched (longer phrases win)
                candidates.append((-len(n.split()), -len(n), name))
                break
    if not candidates:
        return {
            "class": None,
            "where": {},
            "max_results": 50,
            "purpose": (
                "fallback parser: no ontology class name appeared in the "
                "prompt. Configure an LLM (set OPENAI_API_KEY) for richer NL "
                "handling, or use the structured form instead."
            ),
        }
    candidates.sort()
    chosen = candidates[0][2]
    return {
        "class": chosen,
        "where": {},
        "max_results": 50,
        "purpose": (
            f"fallback parser: matched class {chosen!r} by name. "
            "No attribute filters extracted — LLM would do that."
        ),
    }
