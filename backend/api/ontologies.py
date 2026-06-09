"""Ontology + mapping management endpoints + structured ontology query.

Phase 1 surface — see docs/ontology.md.

Upload accepts both YAML and JSON. The structured query endpoint lets
the playground (and tests) drive the OntologyResolver without needing
the NL parser that ships in Phase 3.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import yaml
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ..auto_scenario import make_ontology_scenario, scenario_id_for
from ..ontology import (
    Mapping,
    NLParseError,
    Ontology,
    OntologyError,
    OntologyQuery,
    OntologyResolveError,
    collect_attribute_samples,
    inspect_source,
    parse_mapping,
    parse_nl_query,
    parse_ontology,
    suggest_mappings,
)

router = APIRouter(tags=["ontologies"])


# =============================================================================
# Schemas
# =============================================================================
class OntologySummary(BaseModel):
    id: str
    title: str
    namespace: Optional[str] = None
    class_count: int
    has_mapping: bool
    default: bool = False


class StructuredQueryIn(BaseModel):
    """Body for POST /api/ontology-query/structured."""

    ontology: str
    class_: str = Field(alias="class")
    where: dict[str, Any] = Field(default_factory=dict)
    include_relations: list[str] = Field(default_factory=list)
    max_results: int = 50
    purpose: str = ""

    model_config = {"populate_by_name": True}


# =============================================================================
# List / fetch
# =============================================================================
@router.get("/ontologies", response_model=list[OntologySummary])
def list_ontologies(request: Request) -> list[OntologySummary]:
    state = request.app.state.app_state
    reg = state.ontologies
    return [
        OntologySummary(
            id=o.id,
            title=o.title,
            namespace=o.namespace,
            class_count=len(o.classes),
            has_mapping=reg.get_mapping(o.id) is not None,
            default=o.default,
        )
        for o in reg.all()
    ]


@router.get("/ontologies/{ontology_id}")
def get_ontology(ontology_id: str, request: Request, format: str = "json"):
    """Return the full ontology document. `format=json` returns it as
    JSON (default — easier for tooling); `format=yaml` returns the
    YAML text exactly as it would be written to disk."""
    state = request.app.state.app_state
    onto = state.ontologies.get(ontology_id)
    if onto is None:
        raise HTTPException(404, f"unknown ontology {ontology_id!r}")
    data = onto.model_dump(mode="json")
    if format == "yaml":
        return PlainTextResponse(yaml.safe_dump(data, sort_keys=False))
    return data


@router.get("/ontologies/{ontology_id}/classes")
def list_classes(ontology_id: str, request: Request):
    state = request.app.state.app_state
    onto = state.ontologies.get(ontology_id)
    if onto is None:
        raise HTTPException(404, f"unknown ontology {ontology_id!r}")
    return [
        {
            "name": name,
            "description": cls.description,
            "plain_description": cls.plain_description,
            "attributes": [a.model_dump(mode="json") for a in cls.attributes],
            "relations": [r.model_dump(mode="json") for r in cls.relations],
            "identifier_attribute": (
                cls.identifier_attribute().name if cls.identifier_attribute() else None
            ),
        }
        for name, cls in onto.classes.items()
    ]


# =============================================================================
# Upload (multipart) and raw upload (JSON body)
# =============================================================================
@router.post("/ontologies")
async def upload_ontology(request: Request, file: UploadFile = File(...)):
    """Multipart upload. Accepts .yaml/.yml and .json. The file's name
    is informational only — content sniffing in `parse_ontology()`
    decides the format."""
    raw = await file.read()
    try:
        onto = parse_ontology(raw)
    except OntologyError as exc:
        raise HTTPException(400, str(exc))
    state = request.app.state.app_state
    state.ontologies.register(onto)
    return {"id": onto.id, "title": onto.title, "class_count": len(onto.classes)}


class RawOntologyIn(BaseModel):
    """Programmatic upload — pass JSON or YAML as a string in `content`,
    or send a parsed dict in `document`. Exactly one is required."""

    content: Optional[str] = None
    document: Optional[dict[str, Any]] = None


@router.post("/ontologies/raw")
def upload_ontology_raw(body: RawOntologyIn, request: Request):
    if (body.content is None) == (body.document is None):
        raise HTTPException(400, "provide exactly one of `content` or `document`")
    payload = body.content if body.content is not None else body.document
    try:
        onto = parse_ontology(payload)
    except OntologyError as exc:
        raise HTTPException(400, str(exc))
    state = request.app.state.app_state
    state.ontologies.register(onto)
    return {"id": onto.id, "title": onto.title, "class_count": len(onto.classes)}


@router.delete("/ontologies/{ontology_id}")
def delete_ontology(ontology_id: str, request: Request):
    state = request.app.state.app_state
    if state.ontologies.get(ontology_id) is None:
        raise HTTPException(404, f"unknown ontology {ontology_id!r}")
    try:
        state.ontologies.unregister(ontology_id)
    except OntologyError as exc:
        # Built-in / default ontologies refuse deletion.
        raise HTTPException(400, str(exc))
    return {"id": ontology_id, "removed": True}


# =============================================================================
# Mapping suggestions (LLM)
# =============================================================================
class SuggestMappingsIn(BaseModel):
    data_source_ids: list[str] = Field(default_factory=list)


@router.post("/ontologies/{ontology_id}/mappings/suggest")
async def suggest_mappings_endpoint(
    ontology_id: str, body: SuggestMappingsIn, request: Request
):
    """LLM-driven mapping draft. Does NOT save — the operator must PUT
    the (possibly edited) mapping back via /mappings to commit it."""
    state = request.app.state.app_state
    onto = state.ontologies.get(ontology_id)
    if onto is None:
        raise HTTPException(404, f"unknown ontology {ontology_id!r}")
    if not body.data_source_ids:
        # Default to every registered non-default source. Defaults
        # (`products_csv`, `governance_sqlite`, …) are also included so
        # the operator can choose to map against the demo data too.
        body = SuggestMappingsIn(
            data_source_ids=[s.id for s in state.data_sources.specs()]
        )
    schemas = []
    for sid in body.data_source_ids:
        spec = state.data_sources._specs.get(sid)  # type: ignore[attr-defined]
        if spec is None:
            raise HTTPException(404, f"unknown data source {sid!r}")
        schemas.append(inspect_source(spec, state.data_sources))
    mapping = await suggest_mappings(ontology=onto, schemas=schemas, llm=state.llm)
    return {
        "ontology_id": ontology_id,
        "llm": getattr(state.llm, "name", "fake"),
        "schemas": [s.model_dump(mode="json") for s in schemas],
        "mapping": mapping.model_dump(mode="json"),
    }


# =============================================================================
# Mappings
# =============================================================================
@router.get("/ontologies/{ontology_id}/mappings")
def get_mappings(ontology_id: str, request: Request):
    state = request.app.state.app_state
    onto = state.ontologies.get(ontology_id)
    if onto is None:
        raise HTTPException(404, f"unknown ontology {ontology_id!r}")
    mapping = state.ontologies.get_mapping(ontology_id)
    if mapping is None:
        return {"ontology_id": ontology_id, "mappings": {}}
    return mapping.model_dump(mode="json")


class PutMappingIn(BaseModel):
    """Body for PUT /api/ontologies/{id}/mappings.

    Either pass the raw text in `content` (YAML or JSON), or pass the
    parsed mapping body in `document`. Exactly one is required."""

    content: Optional[str] = None
    document: Optional[dict[str, Any]] = None


@router.put("/ontologies/{ontology_id}/mappings")
def put_mappings(ontology_id: str, body: PutMappingIn, request: Request):
    state = request.app.state.app_state
    if state.ontologies.get(ontology_id) is None:
        raise HTTPException(404, f"unknown ontology {ontology_id!r}")
    if (body.content is None) == (body.document is None):
        raise HTTPException(400, "provide exactly one of `content` or `document`")
    payload = body.content if body.content is not None else body.document
    try:
        mapping = parse_mapping(payload)
    except OntologyError as exc:
        raise HTTPException(400, str(exc))
    if mapping.ontology_id != ontology_id:
        raise HTTPException(
            400,
            f"mapping.ontology_id ({mapping.ontology_id!r}) does not match "
            f"path id ({ontology_id!r})",
        )
    # Validate every referenced class exists in the ontology
    onto = state.ontologies.require(ontology_id)
    unknown_classes = sorted(set(mapping.mappings.keys()) - set(onto.classes.keys()))
    if unknown_classes:
        raise HTTPException(
            400,
            f"mapping references unknown class(es): {unknown_classes}",
        )
    state.ontologies.save_mapping(mapping)
    return {"ontology_id": ontology_id, "saved": True}


# =============================================================================
# Per-class lookup-scenario generation (opt-in chip creation)
# =============================================================================
@router.post("/ontologies/{ontology_id}/classes/{class_name}/scenario")
def generate_lookup_scenario(ontology_id: str, class_name: str, request: Request):
    """Create (or refresh) the autonomous SC-ONTO-<onto>-<class> lookup
    chip for this class. Operator must opt in by clicking; not automatic
    on mapping save."""
    state = request.app.state.app_state
    onto = state.ontologies.get(ontology_id)
    if onto is None:
        raise HTTPException(404, f"unknown ontology {ontology_id!r}")
    if class_name not in onto.classes:
        raise HTTPException(
            404, f"ontology {ontology_id!r} has no class {class_name!r}"
        )
    mapping = state.ontologies.get_mapping(ontology_id)
    cm = mapping.for_class(class_name) if mapping else None
    if cm is None or not cm.sources:
        raise HTTPException(
            400,
            f"class {class_name!r} has no source bindings — save a mapping first",
        )
    scenario = make_ontology_scenario(
        ontology=onto, class_name=class_name, mapping=mapping
    )
    state.scenarios.register(scenario)
    return {
        "scenario_id": scenario_id_for(ontology_id, class_name),
        "title": scenario["title"],
        "binding_count": len(cm.sources),
    }


@router.delete("/ontologies/{ontology_id}/classes/{class_name}/scenario")
def remove_lookup_scenario(ontology_id: str, class_name: str, request: Request):
    """Remove the autonomous chip for this class (does not touch the mapping)."""
    state = request.app.state.app_state
    sid = scenario_id_for(ontology_id, class_name)
    if state.scenarios.get(sid) is None:
        raise HTTPException(404, f"no chip {sid!r} to remove")
    state.scenarios.unregister(sid)
    return {"scenario_id": sid, "removed": True}


# =============================================================================
# Query endpoints
# =============================================================================
def _facts_to_response(oq: OntologyQuery, facts: list) -> dict:
    return {
        "ontology": oq.ontology,
        "class": oq.class_,
        "where": oq.where,
        "purpose": oq.purpose,
        "fact_count": len(facts),
        "facts": [
            {
                "source": f.ref.source,
                "ontology_type": f.ref.ontology_type,
                "id": f.ref.id,
                "title": f.payload.get("title"),
                "summary": f.payload.get("summary"),
                "via_ontology": f.payload.get("via_ontology"),
                "via_source_binding": f.payload.get("via_source_binding"),
            }
            for f in facts
        ],
    }


@router.post("/ontology-query/structured")
def run_structured_query(body: StructuredQueryIn, request: Request):
    state = request.app.state.app_state
    oq = OntologyQuery(
        ontology=body.ontology,
        **{"class": body.class_},
        where=body.where,
        include_relations=body.include_relations,
        max_results=body.max_results,
        purpose=body.purpose,
    )
    try:
        facts = state.ontology_resolver.resolve_query(oq)
    except OntologyResolveError as exc:
        raise HTTPException(400, str(exc))
    return _facts_to_response(oq, facts)


class NLQueryIn(BaseModel):
    """Body for POST /api/ontology-query — operator types in NL, the LLM
    parses it into a structured OntologyQuery, the resolver runs it."""

    ontology: str
    prompt: str
    max_results: int = 50


@router.post("/ontology-query")
async def run_nl_query(body: NLQueryIn, request: Request):
    state = request.app.state.app_state
    onto = state.ontologies.get(body.ontology)
    if onto is None:
        raise HTTPException(404, f"unknown ontology {body.ontology!r}")
    try:
        # Schema-aware: pass the bound sources' actual sample values to
        # the LLM so it normalises human-readable filter forms (e.g.
        # "Dutch") to the data shape (e.g. "NL").
        samples = collect_attribute_samples(
            onto, state.ontologies.get_mapping(onto.id), state.data_sources
        )
        oq = await parse_nl_query(
            body.prompt, onto, state.llm, attribute_samples=samples
        )
    except NLParseError as exc:
        raise HTTPException(400, str(exc))
    # Honour caller's max_results override if they passed one
    if body.max_results and body.max_results != 50:
        oq = oq.model_copy(update={"max_results": body.max_results})
    try:
        facts = state.ontology_resolver.resolve_query(oq)
    except OntologyResolveError as exc:
        raise HTTPException(400, str(exc))
    out = _facts_to_response(oq, facts)
    out["llm"] = getattr(state.llm, "name", "fake")
    return out
