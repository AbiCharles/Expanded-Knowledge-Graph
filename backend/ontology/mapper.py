"""LLM-driven ontology → data-source mapping suggestions.

Given an ontology + a list of registered data source schemas, produce a
draft Mapping document the operator can review and confirm. The LLM is
called once per (class × source) pair; with no LLM available
(FakeLLMClient) the mapper falls back to fuzzy name matching so the UI
is still useful without credentials.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from .models import ClassMapping, Mapping, Ontology, OntologyClass, SourceBinding
from .schema_introspect import ColumnInfo, SourceSchema, TableInfo

log = logging.getLogger(__name__)


_MAPPER_SYSTEM = """You map an ontology class onto a data source's table.

Given:
  - an ontology class (name + attributes with types)
  - a candidate table from a data source (table name + columns with types
    and a few sample values)

Decide whether this table can back this class. If it can:
  - Pick the column that holds the class's identifier attribute
  - For each ontology attribute, pick the column that holds it (or null
    if no good match)
  - Score your overall confidence in this mapping from 0.0 to 1.0

Heuristics:
  - Names matter (case- and underscore-insensitive): supplier_id ↔ supplierId ↔ vendor_id (lower confidence)
  - Types should be compatible (string ↔ varchar/text/varchar; integer ↔ bigint/int; decimal ↔ numeric/float)
  - Sample values help disambiguate when names are ambiguous
  - Confidence ≥ 0.85 = obvious mapping, 0.6–0.85 = plausible, < 0.6 = guess

Respond with strict JSON only:
{
  "applicable": boolean,         // false if no reasonable mapping
  "identifier_column": string|null,
  "attribute_map": { "<ontology_attr>": "<column_name>"|null, ... },
  "confidence": float,           // 0.0–1.0
  "rationale": string            // 1 short sentence
}"""


async def suggest_mappings(
    *,
    ontology: Ontology,
    schemas: list[SourceSchema],
    llm: Any,
) -> Mapping:
    """Return a Mapping draft (NOT persisted) covering each ontology class.

    For every (class, source-table) pair where introspection found columns,
    we call the LLM (or a deterministic fallback) and emit a SourceBinding
    if the proposal is `applicable`. Multiple bindings per class are
    allowed — the resolver fans out at query time.
    """
    use_llm = getattr(llm, "name", "") not in ("fake", "")
    out_mappings: dict[str, ClassMapping] = {}
    for class_name, class_def in ontology.classes.items():
        bindings: list[SourceBinding] = []
        for schema in schemas:
            for table in schema.tables:
                if not table.columns:
                    continue
                proposal = await _propose_one(
                    class_name=class_name,
                    class_def=class_def,
                    schema=schema,
                    table=table,
                    llm=llm,
                    use_llm=use_llm,
                )
                if proposal is None:
                    continue
                bindings.append(proposal)
        out_mappings[class_name] = ClassMapping(sources=bindings)
    return Mapping(ontology_id=ontology.id, mappings=out_mappings)


# =============================================================================
# Single (class × table) proposal
# =============================================================================
async def _propose_one(
    *,
    class_name: str,
    class_def: OntologyClass,
    schema: SourceSchema,
    table: TableInfo,
    llm: Any,
    use_llm: bool,
) -> Optional[SourceBinding]:
    if use_llm:
        try:
            parsed = await _llm_propose(class_name, class_def, table, llm)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "LLM mapping for %s × %s/%s failed (%s) — falling back",
                class_name, schema.source_id, table.name, exc,
            )
            parsed = _fallback_propose(class_def, table)
        suggested_by = "llm"
    else:
        parsed = _fallback_propose(class_def, table)
        suggested_by = "fallback"

    if not parsed.get("applicable"):
        return None
    identifier_column = parsed.get("identifier_column")
    if not identifier_column:
        return None
    raw_map = parsed.get("attribute_map") or {}
    # Drop attributes mapped to null and coerce keys/values to strings.
    attribute_map: dict[str, str] = {
        str(attr): str(col)
        for attr, col in raw_map.items()
        if col is not None
    }
    if not attribute_map:
        return None
    return SourceBinding(
        data_source=schema.source_id,
        identifier_column=str(identifier_column),
        attribute_map=attribute_map,
        confidence=_clamp_float(parsed.get("confidence")),
        suggested_by=suggested_by,
        notes=parsed.get("rationale"),
    )


async def _llm_propose(
    class_name: str,
    class_def: OntologyClass,
    table: TableInfo,
    llm: Any,
) -> dict[str, Any]:
    user_msg = (
        f"Ontology class: {class_name}\n"
        f"Class description: {class_def.description or '(none)'}\n"
        f"Class attributes:\n"
        + "\n".join(
            f"  - {a.name} (type={a.type}"
            + (", identifier" if a.identifier else "")
            + (", required" if a.required else "")
            + ")"
            for a in class_def.attributes
        )
        + f"\n\nCandidate table: {table.name}\n"
        f"Columns:\n"
        + "\n".join(
            f"  - {c.name} (type={c.type}"
            + (f", samples={c.sample_values[:3]}" if c.sample_values else "")
            + ")"
            for c in table.columns
        )
        + "\n\nReturn JSON only."
    )
    raw = await llm.complete(
        system=_MAPPER_SYSTEM, user=user_msg, response_format="json", temperature=0.1,
    )
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("LLM response was not a JSON object")
    return parsed


# =============================================================================
# Deterministic fallback (used when LLM unavailable or errors)
# =============================================================================
def _fallback_propose(class_def: OntologyClass, table: TableInfo) -> dict[str, Any]:
    """Name-based fuzzy matcher. Conservative — only emits a binding when
    every required attribute has a plausible column match."""
    column_names = [c.name for c in table.columns]
    column_lookup = {_norm(c): c for c in column_names}

    attribute_map: dict[str, Optional[str]] = {}
    matched = 0
    for attr in class_def.attributes:
        col = column_lookup.get(_norm(attr.name))
        attribute_map[attr.name] = col
        if col is not None:
            matched += 1

    identifier_attr = class_def.identifier_attribute()
    identifier_column = (
        attribute_map.get(identifier_attr.name) if identifier_attr else None
    )
    if not identifier_column or matched == 0:
        return {"applicable": False, "confidence": 0.0}

    confidence = matched / max(1, len(class_def.attributes))
    return {
        "applicable": True,
        "identifier_column": identifier_column,
        "attribute_map": attribute_map,
        "confidence": round(confidence, 2),
        "rationale": (
            f"Name-match fallback: {matched}/{len(class_def.attributes)} "
            f"attribute(s) matched a column."
        ),
    }


# =============================================================================
# Helpers
# =============================================================================
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _norm(s: str) -> str:
    return _NON_ALNUM.sub("", (s or "").lower())


def _clamp_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, f))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
