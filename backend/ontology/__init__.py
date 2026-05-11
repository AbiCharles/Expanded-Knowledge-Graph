"""Ontology layer: upload an ontology, map it to registered data sources,
let scenarios bind data via ontology classes. See docs/ontology.md."""
from .cypher_safety import CypherSafetyError, assert_read_only, is_read_only
from .loader import OntologyError, OntologyRegistry, parse_mapping, parse_ontology
from .mapper import suggest_mappings
from .nl_query import NLParseError, collect_attribute_samples, parse_nl_query
from .models import (
    Attribute,
    ClassMapping,
    Mapping,
    Ontology,
    OntologyClass,
    OntologyQuery,
    Relation,
    RelationMapping,
    SourceBinding,
)
from .resolver import OntologyResolveError, OntologyResolver, substitute_payload_refs
from .schema_introspect import ColumnInfo, SourceSchema, TableInfo, inspect_source

__all__ = [
    "Attribute",
    "ClassMapping",
    "ColumnInfo",
    "CypherSafetyError",
    "Mapping",
    "NLParseError",
    "Ontology",
    "OntologyClass",
    "OntologyError",
    "OntologyQuery",
    "OntologyRegistry",
    "OntologyResolveError",
    "OntologyResolver",
    "Relation",
    "RelationMapping",
    "SourceBinding",
    "SourceSchema",
    "TableInfo",
    "assert_read_only",
    "collect_attribute_samples",
    "inspect_source",
    "is_read_only",
    "parse_mapping",
    "parse_nl_query",
    "parse_ontology",
    "substitute_payload_refs",
    "suggest_mappings",
]
