"""Pydantic models for the ontology layer.

Two documents per ontology, kept as separate files on disk:

  <id>.yaml          → Ontology  (classes, attributes, relations)
  <id>.mappings.yaml → Mapping   (per-class binding to data sources)

See docs/ontology.md for the design rationale and YAML/JSON examples.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Ontology document
# =============================================================================
class Attribute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str = "string"  # string | integer | decimal | boolean | date | datetime
    identifier: bool = False
    required: bool = False
    description: Optional[str] = None


class Relation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    target: str
    cardinality: str = "0..*"  # "1", "0..1", "0..*", "1..*"
    inverse: Optional[str] = None
    description: Optional[str] = None


class OntologyClass(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Optional[str] = None
    attributes: list[Attribute] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)

    def identifier_attribute(self) -> Optional[Attribute]:
        for a in self.attributes:
            if a.identifier:
                return a
        return None


class Ontology(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    namespace: Optional[str] = None
    description: Optional[str] = None
    # Built-in ontologies set this true and refuse deletion via the API —
    # mirrors the same flag on DataSourceSpec.
    default: bool = False
    classes: dict[str, OntologyClass] = Field(default_factory=dict)

    def class_(self, name: str) -> Optional[OntologyClass]:
        return self.classes.get(name)


# =============================================================================
# Mapping document
# =============================================================================
class SourceBinding(BaseModel):
    """One source backing one ontology class.

    `attribute_map` maps ontology attribute names → source column names.
    The OntologyResolver uses this for both input filter translation
    (callers query by attribute, sources see column-keyed filters) and
    output enrichment (per-fact `via_ontology` tag).

    The kind-specific fields (`table`, `query_template`,
    `http_path_template`) tell each connector how to fetch data for this
    class. Without them connectors fall back to whatever the source spec
    declared (back-compat with the pre-3.C source spec shape); future
    sources should rely on these fields exclusively.
    """

    model_config = ConfigDict(extra="forbid")

    data_source: str
    identifier_column: str
    attribute_map: dict[str, str] = Field(default_factory=dict)
    # Kind-specific binding hints used by the underlying KnowledgeResolver
    # at query time. All optional — connectors fall back to source-spec
    # config when absent.
    table: Optional[str] = None              # SQLite/Postgres: which table
    query_template: Optional[str] = None     # Custom SQL with :params; overrides `table`
    http_path_template: Optional[str] = None # HTTP: e.g. "/items/{id}"
    confidence: Optional[float] = None
    suggested_by: Optional[str] = None  # "llm" | "operator" | "builtin"
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    notes: Optional[str] = None


class RelationMapping(BaseModel):
    """How to traverse a relation to fetch related entities.

    Phase 1 stores this but does not honour `include_relations` yet.
    Kept in the schema so authored mapping docs survive a Phase 3 upgrade.
    """

    model_config = ConfigDict(extra="forbid")

    target: str
    join: dict[str, Any] = Field(default_factory=dict)


class ClassMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[SourceBinding] = Field(default_factory=list)
    relations: dict[str, RelationMapping] = Field(default_factory=dict)


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ontology_id: str
    mappings: dict[str, ClassMapping] = Field(default_factory=dict)

    def for_class(self, class_name: str) -> Optional[ClassMapping]:
        return self.mappings.get(class_name)


# =============================================================================
# Query model
# =============================================================================
class OntologyQuery(BaseModel):
    """Structured query against the ontology — what scenarios and the
    playground both produce and what `OntologyResolver.resolve_query()`
    consumes."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ontology: str
    class_: str = Field(alias="class")
    where: dict[str, Any] = Field(default_factory=dict)
    include_relations: list[str] = Field(default_factory=list)
    max_results: int = 50
    purpose: str = ""
